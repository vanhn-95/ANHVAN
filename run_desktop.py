#!/usr/bin/env python3
"""Chạy SubAI Studio: python run_desktop.py

Script này làm 3 việc theo đúng thứ tự:
  1. Bật Proxy Server dịch thuật (uvicorn) ngầm bằng subprocess - trên Windows
     không bung thêm cửa sổ CMD nào.
  2. Mở cửa sổ ứng dụng.
  3. Đóng app là tắt luôn server, không để tiến trình mồ côi.

Muốn tự chạy server riêng bên ngoài thì sửa config.ini:
    [proxy]
    auto_start = false
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.proxy_manager import ProxyServerManager, start_background_proxy  # noqa: E402


def main() -> int:
    result = start_background_proxy(log=lambda message: print(f"[proxy] {message}"))
    if not result.ok:
        # Thiếu server thì chỉ bước dịch bị ảnh hưởng - app vẫn mở để làm phụ đề.
        print("[proxy] Bước dịch thuật sẽ không dùng được cho tới khi sửa xong.")

    try:
        from desktop.app import main as launch_app

        return launch_app()
    finally:
        ProxyServerManager.instance().stop()
        print("[proxy] Đã tắt server dịch thuật.")


if __name__ == "__main__":
    raise SystemExit(main())
