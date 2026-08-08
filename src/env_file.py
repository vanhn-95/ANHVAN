"""Đọc file .env mà không cần thư viện ngoài.

Được gọi tự động khi import package ``src`` (xem ``src/__init__.py``) và ở
``server/__init__.py``, nên mọi biến trong .env đã sẵn sàng trước khi các module
khác đọc ``os.environ`` ở cấp module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_env(text: str) -> Dict[str, str]:
    """Parse nội dung .env: bỏ comment, hỗ trợ tiền tố ``export`` và nháy bao ngoài."""
    values: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(path: Optional[Path] = None, override: bool = False) -> Dict[str, str]:
    """Nạp .env vào os.environ. Trả về các biến đã đọc được.

    Mặc định biến môi trường sẵn có thắng file .env (``override=False``), để lệnh
    dạng ``GEMINI_API_KEY=xxx uvicorn ...`` vẫn đè được lên file.
    """
    candidates = [Path(path)] if path else [Path.cwd() / ".env", PROJECT_ROOT / ".env"]

    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        values = parse_env(text)
        for key, value in values.items():
            if override or key not in os.environ:
                os.environ[key] = value
        return values

    return {}
