"""Pipeline "Auto Creator": tải → tách nhạc → sub → viết lại → intro → nhạc → TTS → render.

Dùng lại nguyên các engine của pipeline gốc (downloader, separator, ASR, TTS,
composer) và bổ sung ba bước riêng: viết lại kịch bản, intro 3 giây, nhạc nền mới.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from .app_config import AppConfig
from .asr_engine import ASREngine
from .audio_separator import AudioSeparator
from .intro_maker import DEFAULT_BACKGROUND, IntroMaker
from .media_downloader import MediaDownloader
from .music_mixer import MusicMixer, MusicChoice, pick_music, validate_music_file
from .progress import ProgressReporter
from .providers import PROVIDERS
from .script_writer import MoodResult, ScriptWriter, resolve_intro_text
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
class CreatorConfig:
    """Thông số một lần chạy Bot."""

    source: str = ""
    output_dir: str = str(Path.home() / "SubAI" / "creator")
    source_lang: str = "auto"
    target_lang: str = "vi"
    whisper_model: str = "medium"
    device: str = "auto"

    # AI
    provider: str = "gemini"
    api_key: str = ""
    model: str = ""

    # Bật/tắt từng bước
    separate_audio: bool = True
    rewrite_script: bool = True
    tts_dubbing: bool = True
    voice_clone: bool = False        # giọng đọc TikTok thường dùng giọng chuẩn
    keep_subtitles: bool = True
    burn_subtitles: bool = False
    make_intro: bool = True
    add_music: bool = True
    auto_ducking: bool = True

    # Intro
    intro_text: str = ""
    intro_auto_ai: bool = True
    intro_background: str = DEFAULT_BACKGROUND

    # Nhạc
    music_file: str = ""             # file người dùng tự chọn (ưu tiên)
    music_folder: str = ""           # để trống = assets/royalty_free_music
    music_db: float = -15.0

    keep_intermediates: bool = False

    def validate(self) -> None:
        if not self.source.strip():
            raise ValueError("Chưa nhập link video nguồn.")
        if not self.output_dir.strip():
            raise ValueError("Chưa chọn thư mục xuất kết quả.")
        if self.provider not in PROVIDERS:
            raise ValueError(f"Nhà cung cấp AI không hợp lệ: {self.provider}")
        if (self.rewrite_script or self.intro_auto_ai) and not self.api_key.strip():
            raise ValueError(
                "Bật viết lại kịch bản hoặc intro AI thì phải có API key. "
                "Nhập ở tab “Tuỳ chỉnh nâng cao”."
            )
        if not (-40.0 <= self.music_db <= 0.0):
            raise ValueError("Âm lượng nhạc nền phải nằm trong khoảng -40dB đến 0dB.")
        if self.music_file.strip():
            validate_music_file(self.music_file)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreatorConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "CreatorConfig":
        provider = app_config.provider
        return cls(
            provider=provider,
            api_key=app_config.effective_api_key(provider),
            model=app_config.model_for(provider),
        )


@dataclass
class CreatorResult:
    video: Optional[Path] = None
    subtitle: Optional[Path] = None
    script_text: Optional[Path] = None
    mood: Optional[MoodResult] = None
    music: Optional[MusicChoice] = None
    intro_text: str = ""
    segments: List[Segment] = field(default_factory=list)
    elapsed: float = 0.0

    def outputs(self) -> List[Path]:
        return [p for p in (self.video, self.subtitle, self.script_text) if p]


@dataclass
class StageSpec:
    key: str
    label: str
    weight: float


def plan_stages(config: CreatorConfig) -> List[StageSpec]:
    """Các bước sẽ chạy kèm trọng số cho thanh tiến độ."""
    stages = [
        StageSpec("download", "Tải video nguồn", 8),
        StageSpec("separate", "Tách giọng / nhạc nền", 14 if config.separate_audio else 4),
        StageSpec("asr", "Trích xuất lời thoại", 20),
    ]
    if config.rewrite_script:
        stages.append(StageSpec("rewrite", "AI viết lại kịch bản TikTok", 10))
    if config.add_music:
        stages.append(StageSpec("mood", "Phân tích cảm xúc & chọn nhạc", 5))
    if config.tts_dubbing:
        stages.append(StageSpec("tts", "Lồng tiếng cảm xúc (XTTS-v2)", 22))
    stages.append(StageSpec("mix", "Trộn âm thanh", 6))
    if config.make_intro:
        stages.append(StageSpec("intro", "Tạo intro 3 giây", 7))
    stages.append(StageSpec("render", "Render video hoàn chỉnh", 12))
    return stages


class CreatorPipeline:
    """Chạy trọn quy trình Bot. Huỷ được giữa chừng qua reporter.cancel()."""

    def __init__(self, config: CreatorConfig, reporter: Optional[ProgressReporter] = None) -> None:
        self.config = config
        self.reporter = reporter or ProgressReporter()
        self.stages = plan_stages(config)
        self.workspace = Path(config.output_dir) / "workspace_creator"
        self._cursor = 0
        self._base = 0.0

    def _enter(self, key: str) -> None:
        spec = next(s for s in self.stages if s.key == key)
        total = sum(s.weight for s in self.stages)
        self._cursor += 1
        self.reporter.begin_stage(spec.label, self._cursor, len(self.stages),
                                  self._base, spec.weight / total)
        self.reporter.log(f"[{self._cursor}/{len(self.stages)}] {spec.label}")
        self._base += spec.weight / total
        self.reporter.check_cancelled()

    def _has(self, key: str) -> bool:
        return any(s.key == key for s in self.stages)

    def _writer(self) -> Optional[ScriptWriter]:
        if not self.config.api_key.strip():
            return None
        return ScriptWriter(self.config.provider, self.config.api_key, self.config.model)

    def run(self) -> CreatorResult:
        self.config.validate()
        started = time.time()
        result = CreatorResult()
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        writer = self._writer()

        try:
            # 1. Tải video
            self._enter("download")
            video = MediaDownloader(self.workspace).fetch(self.config.source, self.reporter)
            duration = probe_duration(video)
            if duration:
                self.reporter.log(f"Thời lượng: {human_duration(duration)}")

            # 2. Tách giọng / nhạc nền
            self._enter("separate")
            separator = AudioSeparator(self.workspace, device=self.config.device)
            audio = separator.extract_audio(video, self.reporter)
            separation = (
                separator.separate(audio, self.reporter) if self.config.separate_audio else None
            )
            vocals = separation.vocals if separation else audio
            original_bgm = separation.background if separation else None

            # 3. Trích lời thoại
            self._enter("asr")
            segments = ASREngine(
                model_size=self.config.whisper_model, device=self.config.device
            ).transcribe(vocals, self.reporter, self.config.source_lang)
            result.segments = segments

            stem = safe_filename(Path(self.config.source).stem or "video")

            # 4. AI viết lại kịch bản
            if self._has("rewrite"):
                self._enter("rewrite")
                if writer is None:
                    raise PipelineError("Cần API key để viết lại kịch bản.")
                writer.rewrite(segments, self.reporter)
                result.script_text = output_dir / f"{stem}.script.txt"
                result.script_text.write_text(
                    "\n".join(s.output_text() for s in segments), encoding="utf-8"
                )

            if self.config.keep_subtitles:
                result.subtitle = write_srt(
                    segments, output_dir / f"{stem}.{self.config.target_lang}.srt",
                    use_translation=True,
                )
                self.reporter.log(f"Đã lưu phụ đề: {result.subtitle.name}")

            # 5. Cảm xúc + chọn nhạc
            music_path: Optional[Path] = None
            if self._has("mood"):
                self._enter("mood")
                if self.config.music_file.strip():
                    music_path = validate_music_file(self.config.music_file)
                    result.music = MusicChoice(music_path, "Bạn tự chọn file nhạc")
                    self.reporter.log(f"Dùng nhạc bạn chọn: {music_path.name}")
                else:
                    mood = (writer.analyze_mood(segments, self.reporter)
                            if writer else MoodResult())
                    result.mood = mood
                    folder = Path(self.config.music_folder) if self.config.music_folder else None
                    choice = pick_music(mood.genres, folder)
                    result.music = choice
                    music_path = choice.path
                    if choice.found:
                        self.reporter.log(f"Chọn nhạc: {choice.path.name} ({choice.reason})")
                    else:
                        self.reporter.log(f"⚠ {choice.reason} - bỏ qua bước ghép nhạc.")

            # 6. Lồng tiếng
            voice_track: Optional[Path] = None
            if self._has("tts"):
                self._enter("tts")
                tts = TTSEngine(self.workspace, device=self.config.device,
                                voice_clone=self.config.voice_clone)
                speaker = None
                if self.config.voice_clone:
                    speaker = tts.extract_speaker_sample(vocals, segments)
                    if speaker is None:
                        raise PipelineError(
                            "Không trích được giọng mẫu để clone. Tắt voice cloning "
                            "hoặc chọn file giọng mẫu."
                        )
                voice_track = tts.synthesize_track(
                    segments, self.config.target_lang, duration, self.reporter, speaker
                )

            # 7. Trộn âm thanh
            self._enter("mix")
            mixer = MusicMixer(self.workspace, self.config.music_db, self.config.auto_ducking)
            if voice_track is not None:
                final_audio = mixer.mix(
                    voice_track, music_path, self.reporter,
                    original_bgm=original_bgm, duration=duration,
                )
            elif music_path is not None:
                final_audio = mixer.mix(audio, music_path, self.reporter, duration=duration)
            else:
                final_audio = None
                self.reporter.log("Giữ nguyên âm thanh gốc.")

            body = video
            if final_audio is not None:
                body = mixer.replace_audio(
                    video, final_audio, self.workspace / "body.mp4", self.reporter
                )

            # 8. Intro
            if self._has("intro"):
                self._enter("intro")
                text = resolve_intro_text(
                    self.config.intro_text, self.config.intro_auto_ai,
                    writer, segments, self.reporter,
                )
                result.intro_text = text
                maker = IntroMaker(self.workspace, self.config.intro_background)
                intro = maker.build(text, body, self.reporter)
                body = maker.prepend(
                    intro, body, self.workspace / "with_intro.mp4", self.reporter
                )

            # 9. Render cuối
            self._enter("render")
            final_path = output_dir / f"{stem}.tiktok.mp4"
            if self.config.burn_subtitles and result.subtitle:
                # Burn-in phải re-encode; intro đã nằm trước nên phụ đề sẽ lệch 3 giây.
                self.reporter.log(
                    "⚠ Burn-in phụ đề khi có intro sẽ lệch mốc thời gian - "
                    "xuất phụ đề rời (.srt) thay vì ghi chết."
                )
            shutil.copy2(body, final_path)
            result.video = final_path
            self.reporter.progress(1.0)

            result.elapsed = time.time() - started
            self.reporter.log(f"✅ Xong sau {human_duration(result.elapsed)}: {final_path.name}")
            return result

        except CancelledError:
            self.reporter.log("⛔ Đã dừng Bot.")
            raise
        finally:
            if not self.config.keep_intermediates:
                shutil.rmtree(self.workspace, ignore_errors=True)
