"""Render video cuối: mix auto-ducking, mux audio, burn phụ đề."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .progress import ProgressReporter
from .utils import run_ffmpeg


class VideoComposer:
    """Ghép track lồng tiếng + BGM vào video gốc."""

    def __init__(
        self,
        workspace: Path,
        auto_ducking: bool = True,
        ducking_db: float = -12.0,
    ) -> None:
        self.workspace = Path(workspace)
        self.auto_ducking = auto_ducking
        self.ducking_db = ducking_db

    def mix_audio(
        self,
        dubbed: Path,
        background: Optional[Path],
        reporter: ProgressReporter,
    ) -> Path:
        """Trộn lời lồng tiếng với nhạc nền, hạ BGM khi có thoại."""
        if background is None:
            reporter.log("Không có track nhạc nền riêng - dùng thẳng track lồng tiếng.")
            return dubbed

        output = self.workspace / "final_audio.wav"
        if self.auto_ducking:
            reporter.log(f"Mix auto-ducking (BGM giảm {abs(self.ducking_db):.0f}dB khi có thoại)...")
            # sidechaincompress: [bgm] bị nén theo mức tín hiệu của [voice].
            ratio = max(2.0, min(20.0, abs(self.ducking_db) / 2.0))
            filter_complex = (
                "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[voice];"
                "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[bgm];"
                "[voice]asplit=2[voice_mix][voice_sc];"
                f"[bgm][voice_sc]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:"
                "attack=20:release=400[bgm_ducked];"
                "[voice_mix][bgm_ducked]amix=inputs=2:duration=longest:normalize=0,"
                "alimiter=limit=0.95[out]"
            )
        else:
            reporter.log("Mix lời lồng tiếng với nhạc nền (không ducking)...")
            filter_complex = (
                "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[out]"
            )

        run_ffmpeg([
            "-i", str(dubbed), "-i", str(background),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-ar", "44100", str(output),
        ])
        return output

    def render(
        self,
        video: Path,
        audio: Optional[Path],
        output: Path,
        reporter: ProgressReporter,
        subtitles: Optional[Path] = None,
    ) -> Path:
        """Xuất video cuối. audio=None nghĩa là giữ nguyên tiếng gốc."""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        reporter.log(f"Render video: {output.name}")

        args: List[str] = ["-i", str(video)]
        if audio:
            args += ["-i", str(audio)]

        if subtitles:
            # Escape cho filter graph: ffmpeg cần thoát ':' và '\' trong đường dẫn.
            escaped = str(subtitles).replace("\\", "/").replace(":", r"\:")
            args += [
                "-vf",
                f"subtitles='{escaped}':force_style='FontSize=22,Outline=1,Shadow=0'",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            ]
        else:
            args += ["-c:v", "copy"]

        if audio:
            args += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            args += ["-c:a", "copy"]

        args.append(str(output))
        run_ffmpeg(args)
        reporter.progress(1.0)
        return output
