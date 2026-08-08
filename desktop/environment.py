"""Kiểm tra môi trường: engine nào sẵn sàng, engine nào thiếu."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import List

from src.utils import ffmpeg_path, module_available


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True
    fix: str = ""

    @property
    def icon(self) -> str:
        if self.ok:
            return "✅"
        return "❌" if self.required else "⚠"


def _module_check(name: str, module: str, purpose: str, fix: str, required: bool = True) -> Check:
    ok = module_available(module)
    return Check(
        name=name,
        ok=ok,
        detail=purpose if ok else f"Thiếu - {purpose} sẽ không dùng được",
        required=required,
        fix="" if ok else fix,
    )


def _gpu_check() -> Check:
    if not module_available("torch"):
        return Check(
            "GPU / CUDA", False,
            "Thiếu PyTorch - mọi engine AI đều không chạy được",
            required=True,
            fix="pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121",
        )
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            return Check("GPU / CUDA", True, f"{name} - {vram:.1f} GB VRAM")
        return Check(
            "GPU / CUDA", False,
            f"PyTorch {torch.__version__} chạy CPU - xử lý sẽ rất chậm",
            required=False,
            fix="Cài driver NVIDIA + bản torch CUDA 12.1",
        )
    except Exception as exc:
        return Check("GPU / CUDA", False, f"Lỗi khi dò GPU: {exc}", required=False)


def run_checks() -> List[Check]:
    """Danh sách trạng thái phụ thuộc, hiển thị ở tab Môi trường."""
    ffmpeg = ffmpeg_path()
    checks = [
        Check(
            "Python", True,
            f"{platform.python_version()} ({sys.executable})",
        ),
        Check(
            "FFmpeg", bool(ffmpeg),
            ffmpeg or "Không tìm thấy trong PATH - bắt buộc phải có",
            fix="" if ffmpeg else "Tải tại ffmpeg.org rồi thêm vào PATH",
        ),
        _gpu_check(),
        _module_check(
            "yt-dlp", "yt_dlp", "Tải video từ URL",
            "pip install yt-dlp", required=False,
        ),
        _module_check(
            "Demucs", "demucs", "Tách vocal / nhạc nền",
            "pip install demucs", required=False,
        ),
        _module_check(
            "Faster-Whisper", "faster_whisper", "Trích xuất phụ đề (ASR)",
            "pip install faster-whisper",
        ),
        _module_check(
            "Coqui TTS", "TTS", "Lồng tiếng XTTS-v2",
            "pip install TTS", required=False,
        ),
        _module_check(
            "Rubber Band", "pyrubberband", "Căn tốc độ giọng đọc chất lượng cao",
            "pip install pyrubberband (cần rubberband-cli)", required=False,
        ),
    ]
    return checks


def blocking_problems(checks: List[Check]) -> List[Check]:
    return [c for c in checks if c.required and not c.ok]
