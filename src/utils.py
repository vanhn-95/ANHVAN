"""Tiện ích dùng chung: ffmpeg, SRT, đường dẫn."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


class PipelineError(RuntimeError):
    """Lỗi nghiệp vụ của pipeline - hiển thị thẳng cho người dùng."""


class CancelledError(PipelineError):
    """Người dùng bấm Dừng."""


@dataclass
class Segment:
    """Một câu thoại với mốc thời gian (giây)."""

    start: float
    end: float
    text: str
    translated: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def output_text(self) -> str:
        return self.translated or self.text


def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def ffprobe_path() -> Optional[str]:
    return shutil.which("ffprobe")


def require_ffmpeg() -> str:
    exe = ffmpeg_path()
    if not exe:
        raise PipelineError(
            "Không tìm thấy FFmpeg trong PATH. Cài FFmpeg rồi khởi động lại ứng dụng."
        )
    return exe


def run_ffmpeg(args: Sequence[str], log=None) -> None:
    """Chạy ffmpeg với các tham số đã cho (không kèm tên chương trình)."""
    cmd = [require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args]
    if log:
        log(f"$ ffmpeg {' '.join(args)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise PipelineError("FFmpeg lỗi:\n" + "\n".join(tail))


def probe_duration(media: Path) -> float:
    """Độ dài media tính bằng giây; trả 0.0 nếu không xác định được."""
    exe = ffprobe_path()
    if not exe:
        return 0.0
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def safe_filename(name: str, fallback: str = "video") -> str:
    """Bỏ ký tự không hợp lệ trên Windows/Linux, giữ lại tiếng Việt."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return cleaned[:120] or fallback


def format_timestamp(seconds: float) -> str:
    """Định dạng mốc thời gian SRT: HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments: Iterable[Segment], path: Path, use_translation: bool = False) -> Path:
    lines: List[str] = []
    for index, seg in enumerate(segments, start=1):
        text = seg.translated if use_translation else seg.text
        text = (text or "").strip()
        if not text:
            continue
        lines.append(str(index))
        lines.append(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}")
        lines.append(text)
        lines.append("")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def module_available(name: str) -> bool:
    """Kiểm tra module có import được không mà không thực sự nạp nó."""
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def resolve_device(preference: str) -> str:
    """Chuyển 'auto' thành 'cuda'/'cpu' tuỳ máy."""
    if preference in ("cuda", "cpu"):
        return preference
    try:
        import torch  # noqa: PLC0415 - nạp lazy, chỉ khi thực sự cần

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
