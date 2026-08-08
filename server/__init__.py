"""Proxy Server dịch thuật - giữ API key phía server."""

import sys
from pathlib import Path

# Docker image chỉ copy server/ + src/env_file.py, nên thêm project root vào path
# để import được loader .env.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.env_file import load_dotenv  # noqa: E402

load_dotenv()
