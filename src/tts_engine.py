"""Lồng tiếng AI (XTTS-v2) và căn khớp thời lượng theo mốc phụ đề."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from .progress import ProgressReporter
from .utils import (
    PipelineError,
    Segment,
    module_available,
    probe_duration,
    resolve_device,
    run_ffmpeg,
)

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
SAMPLE_RATE = 24000
MIX_CHUNK = 32  # số clip tối đa trong một filter graph amix


class TTSEngine:
    """Sinh giọng đọc cho từng câu rồi ghép lên đúng mốc thời gian gốc."""

    def __init__(
        self,
        workspace: Path,
        device: str = "auto",
        voice_clone: bool = True,
        max_speed_ratio: float = 1.35,
    ) -> None:
        self.workspace = Path(workspace)
        self.device = device
        self.voice_clone = voice_clone
        self.max_speed_ratio = max_speed_ratio
        self._tts = None
        self.clips_dir = self.workspace / "tts_clips"

    @staticmethod
    def available() -> bool:
        return module_available("TTS")

    # ------------------------------------------------------------------ model
    def _load(self, reporter: ProgressReporter):
        if self._tts is not None:
            return self._tts
        if not self.available():
            raise PipelineError(
                "Thiếu Coqui TTS nên không lồng tiếng được. Cài bằng: pip install TTS"
            )
        from TTS.api import TTS  # noqa: PLC0415

        device = resolve_device(self.device)
        reporter.log(f"Nạp model XTTS-v2 trên {device.upper()} (lần đầu sẽ tải model)...")
        self._tts = TTS(XTTS_MODEL).to(device)
        return self._tts

    # ------------------------------------------------------- giọng tham chiếu
    def extract_speaker_sample(self, vocals: Path, segments: Sequence[Segment]) -> Optional[Path]:
        """Cắt ~15 giây thoại rõ nhất từ vocal gốc làm mẫu voice cloning."""
        candidates = sorted(
            (s for s in segments if 2.0 <= s.duration <= 12.0),
            key=lambda s: s.duration,
            reverse=True,
        )[:3]
        if not candidates:
            return None

        parts: List[Path] = []
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        for index, seg in enumerate(candidates):
            part = self.clips_dir / f"speaker_{index}.wav"
            run_ffmpeg([
                "-ss", f"{seg.start:.3f}", "-t", f"{seg.duration:.3f}",
                "-i", str(vocals), "-ac", "1", "-ar", str(SAMPLE_RATE), str(part),
            ])
            parts.append(part)

        sample = self.workspace / "speaker_reference.wav"
        if len(parts) == 1:
            parts[0].replace(sample)
            return sample

        list_file = self.clips_dir / "speaker_parts.txt"
        list_file.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
        )
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(sample)])
        return sample

    # -------------------------------------------------------------- tổng hợp
    def synthesize_track(
        self,
        segments: Sequence[Segment],
        language: str,
        total_duration: float,
        reporter: ProgressReporter,
        speaker_wav: Optional[Path] = None,
    ) -> Path:
        """Tạo một track lồng tiếng dài bằng video, mỗi câu đúng mốc thời gian."""
        tts = self._load(reporter)
        self.clips_dir.mkdir(parents=True, exist_ok=True)

        if self.voice_clone and not speaker_wav:
            raise PipelineError("Bật voice cloning nhưng không có file giọng mẫu.")

        clips: List[tuple[float, Path]] = []
        for index, seg in enumerate(segments):
            reporter.check_cancelled()
            text = seg.output_text().strip()
            if not text:
                continue

            raw_clip = self.clips_dir / f"seg_{index:05d}_raw.wav"
            kwargs = {"text": text, "language": language, "file_path": str(raw_clip)}
            if self.voice_clone and speaker_wav:
                kwargs["speaker_wav"] = str(speaker_wav)
            try:
                tts.tts_to_file(**kwargs)
            except Exception as exc:
                raise PipelineError(f"TTS lỗi ở câu {index + 1}: {exc}") from exc

            fitted = self._fit_duration(raw_clip, seg.duration, index)
            clips.append((seg.start, fitted))
            reporter.progress((index + 1) / max(1, len(segments)))

        if not clips:
            raise PipelineError("Không tổng hợp được câu thoại nào.")

        reporter.log(f"Ghép {len(clips)} đoạn lồng tiếng lên timeline...")
        return self._assemble(clips, total_duration)

    def _fit_duration(self, clip: Path, target: float, index: int) -> Path:
        """Ép clip vừa khung thời gian gốc, giới hạn bởi max_speed_ratio."""
        if target <= 0:
            return clip
        actual = probe_duration(clip)
        if actual <= 0:
            return clip

        ratio = actual / target
        if ratio <= 1.02:  # đủ ngắn, để nguyên rồi đệm im lặng khi ghép
            return clip

        ratio = min(ratio, self.max_speed_ratio)
        fitted = self.clips_dir / f"seg_{index:05d}_fit.wav"
        if module_available("pyrubberband") and module_available("soundfile"):
            import pyrubberband  # noqa: PLC0415
            import soundfile  # noqa: PLC0415

            data, rate = soundfile.read(str(clip))
            soundfile.write(str(fitted), pyrubberband.time_stretch(data, rate, ratio), rate)
        else:
            # atempo chỉ nhận 0.5..2.0 - ratio đã bị chặn dưới 2.0 nên an toàn.
            run_ffmpeg(["-i", str(clip), "-filter:a", f"atempo={ratio:.4f}", str(fitted)])
        return fitted

    def _assemble(self, clips: Sequence[tuple[float, Path]], total_duration: float) -> Path:
        """Đặt từng clip vào đúng offset bằng adelay + amix.

        Video dài có thể có hàng trăm câu; gộp tất cả vào một filter graph sẽ
        vượt giới hạn dòng lệnh, nên mix theo từng nhóm rồi mix các nhóm lại.
        """
        output = self.workspace / "dubbed_track.wav"
        chunks = [clips[i:i + MIX_CHUNK] for i in range(0, len(clips), MIX_CHUNK)]

        if len(chunks) == 1:
            self._mix_group(chunks[0], output, total_duration)
            return output

        partials: List[tuple[float, Path]] = []
        for index, chunk in enumerate(chunks):
            partial = self.clips_dir / f"mix_{index:03d}.wav"
            self._mix_group(chunk, partial, total_duration)
            partials.append((0.0, partial))  # đã nằm đúng offset tuyệt đối

        self._mix_group(partials, output, total_duration)
        return output

    def _mix_group(
        self,
        clips: Sequence[tuple[float, Path]],
        output: Path,
        total_duration: float,
    ) -> None:
        inputs: List[str] = []
        filters: List[str] = []
        labels: List[str] = []

        for index, (start, clip) in enumerate(clips):
            inputs += ["-i", str(clip)]
            delay_ms = int(round(max(0.0, start) * 1000))
            filters.append(
                f"[{index}:a]aresample={SAMPLE_RATE},adelay={delay_ms}|{delay_ms}[d{index}]"
            )
            labels.append(f"[d{index}]")

        filters.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:"
            f"normalize=0,alimiter=limit=0.95[out]"
        )
        args = [
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "[out]",
            "-ar", str(SAMPLE_RATE),
        ]
        if total_duration > 0:
            args += ["-t", f"{total_duration:.3f}"]
        args.append(str(output))
        run_ffmpeg(args)
