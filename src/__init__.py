"""SubAI Engine - core xử lý video đa ngôn ngữ."""

from .env_file import load_dotenv

# Nạp .env ngay khi import package, trước khi config/security_guard đọc os.environ.
load_dotenv()

__version__ = "1.0.0"
