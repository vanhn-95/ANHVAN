"""Chọn nhạc nền và trộn với giọng lồng tiếng (auto-ducking).

Nguồn nhạc: file bạn tự chọn, hoặc thư viện royalty-free trong
``assets/royalty_free_music/``. App không tải nhạc từ TikTok/Douyin - nhạc trên
các nền tảng đó được cấp phép chỉ để dùng trong trình soạn thảo của chính họ.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .progress import ProgressReporter
from .utils import PipelineError, run_ffmpeg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_LIBRARY = PROJECT_ROOT / "assets" / "royalty_free_music"
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}

DEFAULT_MUSIC_DB = -15.0
SAMPLE_RATE = 44100


@dataclass
class MusicChoice:
    path: Optional[Path]
    reason: str
    matched_genre: str = ""

    @property
    def found(self) -> bool:
        return self.path is not None


def _normalize(text: str) -> str:
    """Bỏ dấu tiếng Việt + hạ chữ thường để so khớp tên file dễ hơn."""
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")


def list_library(folder: Optional[Path] = None) -> List[Path]:
    """Liệt kê file nhạc trong thư viện."""
    folder = Path(folder) if folder else MUSIC_LIBRARY
    if not folder.is_dir():
        return []
    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
    )


def pick_music(
    genres: Sequence[str],
    folder: Optional[Path] = None,
    rng: Optional[random.Random] = None,
) -> MusicChoice:
    """Chọn nhạc khớp thể loại AI gợi ý; không khớp thì lấy ngẫu nhiên."""
    tracks = list_library(folder)
    if not tracks:
        target = Path(folder) if folder else MUSIC_LIBRARY
        return MusicChoice(None, f"Thư viện nhạc trống: {target}")

    rng = rng or random.Random()
    for genre in genres:
        needle = _normalize(genre)
        if not needle:
            continue
        matches = [track for track in tracks if needle in _normalize(track.stem)]
        if matches:
            return MusicChoice(rng.choice(matches), f"Khớp thể loại “{genre}”", genre)

    return MusicChoice(rng.choice(tracks), "Không có file khớp thể loại - chọn ngẫu nhiên")


class MusicMixer:
    """Trộn giọng lồng tiếng + nhạc nền mới (+ nhạc nền gốc nếu muốn giữ)."""

    def __init__(
        self,
        workspace: Path,
        music_db: float = DEFAULT_MUSIC_DB,
        ducking: bool = True,
    ) -> None:
        self.workspace = Path(workspace)
        self.music_db = music_db
        self.ducking = ducking
        self.workspace.mkdir(parents=True, exist_ok=True)

    def mix(
        self,
        voice: Path,
        music: Optional[Path],
        reporter: ProgressReporter,
        original_bgm: Optional[Path] = None,
        duration: float = 0.0,
    ) -> Path:
        """Ghép giọng + nhạc. Nhạc bị hạ ``music_db`` và né giọng khi có thoại."""
        if music is None and original_bgm is None:
            return Path(voice)

        output = self.workspace / "creator_audio.wav"
        inputs: List[str] = ["-i", str(voice)]

        # Chỉ tách nhánh sidechain khi thật sự dùng: asplit để hở một output là
        # ffmpeg từ chối chạy ("Filter asplit has an unconnected output").
        needs_key = music is not None and self.ducking
        voice_format = (
            f"[0:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
        )
        if needs_key:
            filters: List[str] = [f"{voice_format},asplit=2[voice_mix][voice_key]"]
            key_stream = "[voice_key]"
        else:
            filters = [f"{voice_format}[voice_mix]"]
            key_stream = ""

        to_mix = ["[voice_mix]"]
        index = 1

        if music is not None:
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            reporter.log(
                f"Ghép nhạc nền: {Path(music).name} ({self.music_db:+.0f}dB"
                f"{', auto-ducking' if self.ducking else ''})"
            )
            filters.append(
                f"[{index}:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:"
                f"channel_layouts=stereo,volume={self.music_db}dB[music_raw]"
            )
            if self.ducking:
                filters.append(
                    f"[music_raw]{key_stream}sidechaincompress="
                    "threshold=0.02:ratio=8:attack=20:release=400[music]"
                )
            else:
                filters.append("[music_raw]anull[music]")
            to_mix.append("[music]")
            index += 1

        if original_bgm is not None:
            inputs += ["-i", str(original_bgm)]
            filters.append(
                f"[{index}:a]aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}:"
                f"channel_layouts=stereo,volume=-20dB[bgm]"
            )
            to_mix.append("[bgm]")
            index += 1

        filters.append(
            f"{''.join(to_mix)}amix=inputs={len(to_mix)}:duration=first:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )

        args = [*inputs, "-filter_complex", ";".join(filters), "-map", "[aout]",
                "-ar", str(SAMPLE_RATE)]
        if duration > 0:
            args += ["-t", f"{duration:.3f}"]
        args.append(str(output))

        run_ffmpeg(args)
        return output

    def replace_audio(self, video: Path, audio: Path, output: Path,
                      reporter: ProgressReporter) -> Path:
        """Thay toàn bộ tiếng của video bằng track đã trộn."""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        reporter.log("Gắn track âm thanh mới vào video...")
        run_ffmpeg([
            "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(output),
        ])
        return output


def ensure_library() -> Path:
    """Tạo sẵn thư mục nhạc kèm README nếu chưa có."""
    MUSIC_LIBRARY.mkdir(parents=True, exist_ok=True)
    readme = MUSIC_LIBRARY / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Thư viện nhạc nền\n\n"
            "Đặt các file nhạc **bạn có quyền sử dụng** vào đây (.mp3, .wav, .m4a...).\n\n"
            "App chọn nhạc theo tên file, nên hãy đặt tên có chứa thể loại để AI khớp "
            "được, ví dụ:\n\n"
            "- `lofi-chill-01.mp3`\n"
            "- `edm-upbeat-hype.mp3`\n"
            "- `piano-buon-nhe.mp3`\n"
            "- `cinematic-epic-tension.mp3`\n\n"
            "## Nguồn nhạc miễn phí bản quyền\n\n"
            "- YouTube Audio Library (studio.youtube.com)\n"
            "- Pixabay Music, Free Music Archive, Incompetech\n\n"
            "Đọc kỹ điều kiện của từng bản nhạc: nhiều bản miễn phí vẫn yêu cầu ghi "
            "nguồn khi dùng thương mại.\n",
            encoding="utf-8",
        )
    return MUSIC_LIBRARY


def validate_music_file(path: str) -> Path:
    """Kiểm tra file nhạc người dùng chọn."""
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise PipelineError(f"Không tìm thấy file nhạc: {candidate}")
    if candidate.suffix.lower() not in AUDIO_SUFFIXES:
        raise PipelineError(
            f"Định dạng nhạc không hỗ trợ: {candidate.suffix}. "
            f"Dùng một trong: {', '.join(sorted(AUDIO_SUFFIXES))}"
        )
    return candidate
