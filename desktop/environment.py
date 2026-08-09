"""Kiểm tra môi trường: engine nào sẵn sàng, engine nào thiếu."""

from __future__ import annotations

import platform
import shutil
import subprocess
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


def has_nvidia_gpu() -> bool:
    """Máy có GPU NVIDIA không - dò được cả khi chưa cài PyTorch.

    Cần biết điều này TRƯỚC khi gợi ý lệnh cài: máy không có NVIDIA mà bảo cài
    bản wheel `cu121` thì lệnh sẽ lỗi hoặc cài về một bản torch vô dụng.
    """
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def torch_install_command() -> str:
    """Lệnh cài PyTorch đúng với phần cứng đang có."""
    if has_nvidia_gpu():
        return ("pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cu121")
    # Không có NVIDIA: bản CPU mặc định từ PyPI. Tuyệt đối không gợi ý cu121.
    return "pip install torch torchaudio"


def _torch_check() -> Check:
    """PyTorch chỉ cần cho Demucs và XTTS - Faster-Whisper không dùng tới nó."""
    if module_available("torch"):
        try:
            import torch

            return Check("PyTorch", True, f"phiên bản {torch.__version__}")
        except Exception as exc:
            return Check("PyTorch", False, f"Cài rồi nhưng import lỗi: {exc}",
                         required=False, fix=torch_install_command())

    return Check(
        "PyTorch", False,
        "Thiếu - cần cho tách nhạc nền (Demucs) và lồng tiếng (XTTS)",
        required=False,
        fix=torch_install_command(),
    )


def _gpu_check() -> Check:
    """Báo trạng thái tăng tốc phần cứng. Không bao giờ chặn app chạy."""
    if not has_nvidia_gpu():
        return Check(
            "GPU / CUDA", False,
            "Đang chạy chế độ CPU (sẽ chậm hơn). Để tối ưu, cần có GPU NVIDIA.",
            required=False,
            fix="",     # cố ý để trống: không có NVIDIA thì không có lệnh nào giúp được
        )

    if not module_available("torch"):
        return Check(
            "GPU / CUDA", False,
            "Máy có GPU NVIDIA nhưng chưa cài PyTorch nên chưa dùng được",
            required=False,
            fix=torch_install_command(),
        )

    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            return Check("GPU / CUDA", True, f"{name} - {vram:.1f} GB VRAM")

        return Check(
            "GPU / CUDA", False,
            "Có GPU NVIDIA nhưng PyTorch đang là bản CPU - xử lý sẽ chậm",
            required=False,
            fix=torch_install_command(),
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
        _torch_check(),
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


def format_missing(checks: List[Check]) -> str:
    """Ghi rõ từng thành phần thiếu kèm lệnh cài, cho hộp thoại cảnh báo."""
    lines: List[str] = []
    for check in checks:
        lines.append(f"• {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"   Lệnh cài đặt: {check.fix}")
    return "\n".join(lines)
