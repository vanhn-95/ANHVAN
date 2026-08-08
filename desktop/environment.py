"""Kiểm tra môi trường: engine nào sẵn sàng, engine nào thiếu."""

from __future__ import annotations

import platform
import shutil
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


def _rubberband_check() -> Check:
    """pyrubberband cần cả module Python lẫn binary `rubberband` trong PATH."""
    has_module = module_available("pyrubberband")
    has_binary = shutil.which("rubberband") is not None

    if has_module and has_binary:
        return Check("Rubber Band", True, "Căn tốc độ giọng đọc giữ nguyên cao độ", required=False)

    if not has_module and not has_binary:
        detail = "Thiếu cả module lẫn binary"
        fix = "pip install pyrubberband + cài rubberband-cli"
    elif not has_binary:
        detail = "Có module Python nhưng thiếu binary `rubberband` trong PATH"
        fix = "Linux: apt install rubberband-cli · Windows: tải từ breakfastquay.com"
    else:
        detail = "Có binary nhưng thiếu module Python"
        fix = "pip install pyrubberband"

    return Check(
        "Rubber Band", False,
        f"{detail} - sẽ tự dùng FFmpeg atempo thay thế (chất lượng thấp hơn một chút)",
        required=False,
        fix=fix,
    )


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
        _rubberband_check(),
    ]
    return checks


def blocking_problems(checks: List[Check]) -> List[Check]:
    return [c for c in checks if c.required and not c.ok]
