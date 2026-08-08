"""Điều phối toàn bộ pipeline: tải -> tách -> ASR -> dịch -> lồng tiếng -> render."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .asr_engine import ASREngine
from .audio_separator import AudioSeparator
from .config import JobConfig
from .media_downloader import MediaDownloader
from .progress import ProgressReporter
from .translator import TranslatorClient
from .tts_engine import TTSEngine
from .utils import (
    CancelledError,
    PipelineError,
    Segment,
    human_duration,
    probe_duration,
    safe_filename,
    write_srt,
)
from .video_composer import VideoComposer


@dataclass
class StageSpec:
    key: str
    label: str
    weight: float


@dataclass
class PipelineResult:
    video: Optional[Path] = None
    subtitle_source: Optional[Path] = None
    subtitle_target: Optional[Path] = None
    dubbed_audio: Optional[Path] = None
    segments: List[Segment] = field(default_factory=list)
    elapsed: float = 0.0
    workspace: Optional[Path] = None

    def outputs(self) -> List[Path]:
        return [p for p in (self.video, self.subtitle_source, self.subtitle_target,
                            self.dubbed_audio) if p]


def plan_stages(config: JobConfig) -> List[StageSpec]:
    """Danh sách bước sẽ chạy, tuỳ theo các tuỳ chọn được bật."""
    stages = [StageSpec("download", "Chuẩn bị video", 10)]
    stages.append(StageSpec("separate", "Tách giọng / nhạc nền", 18 if config.separate_audio else 5))
    stages.append(StageSpec("asr", "Trích xuất phụ đề", 28))
    if config.translate:
        stages.append(StageSpec("translate", "Dịch thuật AI", 10))
    if config.dubbing:
        stages.append(StageSpec("tts", "Lồng tiếng AI", 26))
    stages.append(StageSpec("render", "Render video", 12))
    return stages


class Pipeline:
    """Chạy một job hoàn chỉnh. Có thể huỷ giữa chừng qua reporter.cancel()."""

    def __init__(self, config: JobConfig, reporter: Optional[ProgressReporter] = None) -> None:
        self.config = config
        self.reporter = reporter or ProgressReporter()
        self.stages = plan_stages(config)
        self.workspace = Path(config.output_dir) / "workspace"
        self._stage_cursor = 0
        self._progress_base = 0.0

    # ------------------------------------------------------------- khung chạy
    def _enter(self, key: str) -> None:
        spec = next(s for s in self.stages if s.key == key)
        total_weight = sum(s.weight for s in self.stages)
        self._stage_cursor += 1
        self.reporter.begin_stage(
            spec.label, self._stage_cursor, len(self.stages),
            self._progress_base, spec.weight / total_weight,
        )
        self.reporter.log(f"[{self._stage_cursor}/{len(self.stages)}] {spec.label}")
        self._progress_base += spec.weight / total_weight
        self.reporter.check_cancelled()

    def _has(self, key: str) -> bool:
        return any(s.key == key for s in self.stages)

    # ------------------------------------------------------------------ chạy
    def run(self) -> PipelineResult:
        self.config.validate()
        started = time.time()
        result = PipelineResult(workspace=self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Video nguồn
            self._enter("download")
            downloader = MediaDownloader(self.workspace)
            video = downloader.fetch(self.config.source, self.reporter)
            duration = probe_duration(video)
            if duration:
                self.reporter.log(f"Thời lượng video: {human_duration(duration)}")

            # 2. Audio + tách nền
            self._enter("separate")
            separator = AudioSeparator(self.workspace, self.config.demucs_model, self.config.device)
            audio = separator.extract_audio(video, self.reporter)
            separation = (
                separator.separate(audio, self.reporter) if self.config.separate_audio else None
            )
            vocals = separation.vocals if separation else audio
            background = separation.background if separation else None

            # 3. Phụ đề gốc
            self._enter("asr")
            asr = ASREngine(
                model_size=self.config.whisper_model,
                device=self.config.device,
                compute_type=self.config.compute_type,
                vad_filter=self.config.vad_filter,
            )
            segments = asr.transcribe(vocals, self.reporter, self.config.source_lang)
            result.segments = segments

            stem = safe_filename(Path(self.config.source).stem if not self.config.is_url() else "video")
            result.subtitle_source = write_srt(segments, output_dir / f"{stem}.origin.srt")
            self.reporter.log(f"Đã lưu phụ đề gốc: {result.subtitle_source.name}")

            # 4. Dịch
            if self._has("translate"):
                self._enter("translate")
                translator = TranslatorClient(self.config.proxy_url, self.config.license_key)
                if not translator.health():
                    raise PipelineError(
                        f"Không kết nối được Proxy Server tại {self.config.proxy_url}. "
                        "Kiểm tra server đã chạy chưa."
                    )
                translator.translate_segments(
                    segments, self.config.source_lang, self.config.target_lang, self.reporter
                )
                result.subtitle_target = write_srt(
                    segments, output_dir / f"{stem}.{self.config.target_lang}.srt",
                    use_translation=True,
                )
                self.reporter.log(f"Đã lưu phụ đề dịch: {result.subtitle_target.name}")

            # 5. Lồng tiếng
            final_audio: Optional[Path] = None
            if self._has("tts"):
                self._enter("tts")
                tts = TTSEngine(
                    self.workspace,
                    device=self.config.device,
                    voice_clone=self.config.voice_clone,
                    max_speed_ratio=self.config.max_speed_ratio,
                )
                speaker = Path(self.config.tts_speaker_wav) if self.config.tts_speaker_wav else None
                if self.config.voice_clone and speaker is None:
                    speaker = tts.extract_speaker_sample(vocals, segments)
                    if speaker is None:
                        raise PipelineError(
                            "Không trích được giọng mẫu để clone. Hãy chọn file giọng mẫu thủ công "
                            "hoặc tắt voice cloning."
                        )
                    self.reporter.log("Đã trích giọng mẫu từ vocal gốc.")

                dubbed = tts.synthesize_track(
                    segments, self.config.target_lang, duration, self.reporter, speaker
                )
                result.dubbed_audio = dubbed

                composer = VideoComposer(
                    self.workspace, self.config.auto_ducking, self.config.ducking_db
                )
                final_audio = composer.mix_audio(dubbed, background, self.reporter)

            # 6. Render
            self._enter("render")
            composer = VideoComposer(self.workspace, self.config.auto_ducking, self.config.ducking_db)
            subtitle_for_burn = None
            if self.config.burn_subtitles:
                subtitle_for_burn = result.subtitle_target or result.subtitle_source
            suffix = "dubbed" if final_audio else "sub"
            result.video = composer.render(
                video, final_audio, output_dir / f"{stem}.{self.config.target_lang}.{suffix}.mp4",
                self.reporter, subtitle_for_burn,
            )

            result.elapsed = time.time() - started
            self.reporter.log(f"✅ Hoàn tất sau {human_duration(result.elapsed)}")
            return result

        except CancelledError:
            self.reporter.log("⛔ Đã dừng job.")
            raise
        finally:
            if not self.config.keep_intermediates:
                shutil.rmtree(self.workspace, ignore_errors=True)


def run_job(
    config: JobConfig,
    on_log: Optional[Callable[[str], None]] = None,
) -> PipelineResult:
    """Tiện ích cho script/CLI: chạy pipeline với reporter mặc định."""
    return Pipeline(config, ProgressReporter(on_log=on_log)).run()


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="SubAI Engine - CLI")
    parser.add_argument("source", help="URL video hoặc đường dẫn file")
    parser.add_argument("-o", "--output", default=JobConfig().output_dir, help="Thư mục xuất")
    parser.add_argument("-t", "--target", default="vi", help="Ngôn ngữ đích (mặc định: vi)")
    parser.add_argument("-s", "--source-lang", default="auto", help="Ngôn ngữ nguồn")
    parser.add_argument("-m", "--model", default="medium", help="Model Whisper")
    parser.add_argument("--proxy", default="http://127.0.0.1:8000", help="Proxy Server dịch thuật")
    parser.add_argument("--no-dub", action="store_true", help="Chỉ làm phụ đề, không lồng tiếng")
    parser.add_argument("--burn", action="store_true", help="Ghi phụ đề chết vào video")
    args = parser.parse_args(argv)

    config = JobConfig(
        source=args.source,
        output_dir=args.output,
        source_lang=args.source_lang,
        target_lang=args.target,
        whisper_model=args.model,
        proxy_url=args.proxy,
        dubbing=not args.no_dub,
        burn_subtitles=args.burn,
    )

    try:
        result = run_job(config)
    except PipelineError as exc:
        print(f"Lỗi: {exc}")
        return 1
    except KeyboardInterrupt:
        print("Đã huỷ.")
        return 130

    for path in result.outputs():
        print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
