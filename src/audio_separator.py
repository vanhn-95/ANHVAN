"""Tách vocal / nhạc nền bằng Demucs (HTDemucs v4)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .progress import ProgressReporter
from .utils import PipelineError, module_available, resolve_device, run_ffmpeg


@dataclass
class SeparationResult:
    """Kết quả tách âm thanh.

    ``separated`` = False nghĩa là chạy ở chế độ suy giảm: ``vocals`` là toàn bộ
    audio gốc và ``background`` là None (không có BGM riêng để mix lại).
    """

    vocals: Path
    background: Path | None
    separated: bool


class AudioSeparator:
    """Trích audio khỏi video rồi tách vocal/BGM."""

    def __init__(self, workspace: Path, model: str = "htdemucs", device: str = "auto") -> None:
        self.workspace = Path(workspace)
        self.model = model
        self.device = device
        self.workspace.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return module_available("demucs")

    def extract_audio(self, video: Path, reporter: ProgressReporter) -> Path:
        """Xuất audio 16-bit 44.1kHz stereo từ video."""
        audio = self.workspace / "original_audio.wav"
        reporter.log("Trích xuất audio từ video...")
        run_ffmpeg(
            ["-i", str(video), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(audio)],
        )
        return audio

    def separate(self, audio: Path, reporter: ProgressReporter) -> SeparationResult:
        """Tách vocal/BGM. Không có Demucs thì trả về chế độ suy giảm."""
        if not self.available():
            reporter.log(
                "⚠ Không có Demucs - bỏ qua bước tách nhạc nền. "
                "Độ chính xác ASR có thể giảm và bản render sẽ không giữ được BGM gốc."
            )
            return SeparationResult(vocals=audio, background=None, separated=False)

        out_dir = self.workspace / "demucs"
        out_dir.mkdir(parents=True, exist_ok=True)
        device = resolve_device(self.device)

        reporter.log(f"Tách vocal/BGM bằng Demucs [{self.model}] trên {device.upper()}...")
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", self.model,
            "--two-stems", "vocals",
            "-d", device,
            "-o", str(out_dir),
            str(audio),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        reporter.check_cancelled()
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-8:]
            raise PipelineError("Demucs lỗi:\n" + "\n".join(tail))

        stem_dir = out_dir / self.model / audio.stem
        vocals = stem_dir / "vocals.wav"
        background = stem_dir / "no_vocals.wav"
        if not vocals.exists():
            raise PipelineError(f"Demucs chạy xong nhưng không thấy {vocals}")

        reporter.progress(1.0)
        return SeparationResult(
            vocals=vocals,
            background=background if background.exists() else None,
            separated=True,
        )
