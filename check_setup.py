#!/usr/bin/env python3
"""Chẩn đoán môi trường SubAI Studio.

Chạy:  python check_setup.py

Script này chỉ dùng thư viện chuẩn nên chạy được kể cả khi chưa cài gì. Nó chỉ ra
chính xác đang thiếu gì và phải gõ lệnh nào tiếp theo.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK = "[ OK ]"
FAIL = "[LỖI ]"
WARN = "[ ! ]"

problems: list[str] = []
warnings: list[str] = []


def line(char: str = "-") -> None:
    print(char * 68)


def check_python() -> None:
    print(f"Python      : {platform.python_version()}")
    print(f"Đường dẫn   : {sys.executable}")

    in_venv = sys.prefix != sys.base_prefix
    print(f"Môi trường ảo: {'CÓ - ' + sys.prefix if in_venv else 'KHÔNG'}")

    major, minor = sys.version_info[:2]
    if (major, minor) == (3, 11):
        print(f"{OK} Python 3.11 - đúng phiên bản dự án yêu cầu.")
    elif (major, minor) < (3, 10):
        print(f"{FAIL} Python {major}.{minor} quá cũ. Cần Python 3.11.")
        problems.append("Cài Python 3.11 từ python.org rồi tạo lại venv.")
    else:
        print(f"{WARN} Python {major}.{minor} - dự án chuẩn hoá trên 3.11.")
        if minor >= 12:
            warnings.append(
                f"Python {major}.{minor}: Coqui TTS không cài được, bước lồng tiếng sẽ hỏng. "
                "Nên dùng Python 3.11."
            )

    if not in_venv:
        warnings.append(
            "Đang chạy bằng Python toàn cục, chưa kích hoạt venv. "
            "Xem lệnh tạo venv ở cuối."
        )


def check_module(label: str, module: str, install: str, required: bool) -> bool:
    try:
        found = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        found = False

    if found:
        print(f"{OK} {label}")
        return True

    print(f"{FAIL if required else WARN} {label} - chưa cài")
    (problems if required else warnings).append(f"{label}: {install}")
    return False


def check_ffmpeg() -> None:
    path = shutil.which("ffmpeg")
    if not path:
        print(f"{FAIL} FFmpeg - không có trong PATH")
        problems.append(
            "FFmpeg: Windows `winget install --id Gyan.FFmpeg` rồi MỞ LẠI terminal · "
            "Linux `sudo apt install ffmpeg`"
        )
        return
    try:
        version = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=15
        ).stdout.splitlines()[0]
    except Exception:
        version = path
    print(f"{OK} FFmpeg - {version[:56]}")


def has_nvidia_gpu() -> bool:
    """Có GPU NVIDIA không - quyết định gợi ý bản torch CUDA hay bản CPU."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False


def torch_install_hint() -> str:
    if has_nvidia_gpu():
        return ("pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cu121")
    return "pip install torch torchaudio    (ban CPU - may nay khong co GPU NVIDIA)"


def check_gpu() -> None:
    if has_nvidia_gpu():
        print(f"{OK} GPU NVIDIA - dung duoc tang toc CUDA")
    else:
        print(f"{WARN} Dang chay che do CPU (se cham hon). De toi uu, can co GPU NVIDIA.")
        warnings.append(
            "Khong co GPU NVIDIA: moi buoc AI se chay bang CPU, cham hon nhieu "
            "nhung van chay duoc. Dung cai ban torch cu121."
        )


def check_gui_import() -> None:
    """Thử import đúng đường dẫn mà app dùng - bắt lỗi thật thay vì đoán."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from desktop.app import create_app  # noqa: F401

        print(f"{OK} Import được giao diện (desktop.app)")
    except Exception as exc:
        print(f"{FAIL} Không import được giao diện: {exc.__class__.__name__}: {exc}")
        problems.append(f"Import giao diện lỗi: {exc}")


def check_files() -> None:
    missing = [
        name for name in ("run_desktop.py", "desktop", "src", "requirements.txt")
        if not (ROOT / name).exists()
    ]
    if missing:
        print(f"{FAIL} Thiếu file/thư mục: {', '.join(missing)}")
        problems.append(
            "Đang chạy sai thư mục, hoặc giải nén thiếu. "
            "Hãy cd vào đúng thư mục chứa run_desktop.py."
        )
    else:
        print(f"{OK} Cấu trúc dự án đầy đủ ({ROOT})")


def venv_commands() -> str:
    if platform.system() == "Windows":
        return (
            "  py -3.11 -m venv venv\n"
            "  venv\\Scripts\\activate\n"
            "  pip install -r requirements-desktop.txt\n"
            "  python run_desktop.py"
        )
    return (
        "  python3.11 -m venv venv\n"
        "  source venv/bin/activate\n"
        "  pip install -r requirements-desktop.txt\n"
        "  python run_desktop.py"
    )


def main() -> int:
    line("=")
    print("  CHẨN ĐOÁN MÔI TRƯỜNG SUBAI STUDIO")
    line("=")

    check_python()
    line()
    check_files()
    line()

    print("Bắt buộc để mở được app:")
    check_module("PySide6 (giao diện)", "PySide6", "pip install PySide6-Essentials", True)
    check_ffmpeg()
    line()

    check_gpu()
    line()

    print("Engine AI (thiếu thì bước tương ứng bị tắt, app vẫn mở):")
    check_module("PyTorch", "torch", torch_install_hint(), False)
    check_module("Faster-Whisper (phụ đề)", "faster_whisper", "pip install faster-whisper", False)
    check_module("Demucs (tách nhạc nền)", "demucs", "pip install demucs", False)
    check_module("Coqui TTS (lồng tiếng)", "TTS", "pip install TTS", False)
    check_module("yt-dlp (tải video)", "yt_dlp", "pip install yt-dlp", False)
    line()

    check_gui_import()
    line("=")

    if problems:
        print(f"\n>>> CÓ {len(problems)} LỖI PHẢI SỬA:\n")
        for index, item in enumerate(problems, 1):
            print(f"  {index}. {item}")
        print("\nCác lệnh chuẩn (chạy trong thư mục này):\n")
        print(venv_commands())
    else:
        print("\n>>> KHÔNG CÓ LỖI CHẶN. Mở app bằng lệnh:\n")
        print("  python run_desktop.py")

    if warnings:
        print(f"\n>>> {len(warnings)} cảnh báo (không chặn app chạy):\n")
        for index, item in enumerate(warnings, 1):
            print(f"  {index}. {item}")

    print()
    return 1 if problems else 0


if __name__ == "__main__":
    code = main()
    # Double-click trên Windows: giữ cửa sổ lại để đọc kết quả.
    if platform.system() == "Windows" and not sys.stdout.isatty():
        input("Nhấn Enter để đóng...")
    raise SystemExit(code)
