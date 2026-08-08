"""Lưu cấu hình người dùng vào config.ini (API key, proxy, license).

Khác với ``AppSettings`` (nhớ job gần nhất, dạng JSON trong ~/.subai), file này giữ
những thứ người dùng nhập một lần rồi dùng mãi - quan trọng nhất là GEMINI_API_KEY.

Thứ tự ưu tiên: giá trị trong config.ini (do người dùng nhập ở giao diện) thắng biến
môi trường/.env. Chỉ khi config.ini để trống mới rơi về biến môi trường.
"""

from __future__ import annotations

import configparser
import os
import stat
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("SUBAI_CONFIG", PROJECT_ROOT / "config.ini"))

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_PROXY_URL = "http://127.0.0.1:8000"


class AppConfig:
    """Bọc configparser với các thuộc tính có tên rõ ràng."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else CONFIG_FILE
        self._parser = configparser.ConfigParser()
        self._parser.read_dict({
            "gemini": {"api_key": "", "model": DEFAULT_MODEL},
            "proxy": {"url": DEFAULT_PROXY_URL, "auto_start": "true", "port": "8000"},
            "license": {"key": ""},
        })

    # ------------------------------------------------------------------ đọc/ghi
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        config = cls(path)
        try:
            config._parser.read(config.path, encoding="utf-8")
        except (OSError, configparser.Error):
            pass  # file hỏng thì dùng giá trị mặc định, không làm app chết
        return config

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write(
                "# Cấu hình SubAI Studio - sinh ra từ giao diện.\n"
                "# CHỨA API KEY: đừng commit lên git hay gửi file này cho người khác.\n\n"
            )
            self._parser.write(handle)
        self._restrict_permissions()
        return self.path

    def _restrict_permissions(self) -> None:
        """Chỉ chủ sở hữu đọc được (POSIX). Windows bỏ qua, không có tương đương."""
        try:
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, NotImplementedError):
            pass

    # -------------------------------------------------------------- thuộc tính
    def _get(self, section: str, option: str, fallback: str = "") -> str:
        return self._parser.get(section, option, fallback=fallback).strip()

    def _set(self, section: str, option: str, value: str) -> None:
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, option, value)

    @property
    def gemini_api_key(self) -> str:
        return self._get("gemini", "api_key")

    @gemini_api_key.setter
    def gemini_api_key(self, value: str) -> None:
        self._set("gemini", "api_key", (value or "").strip())

    @property
    def gemini_model(self) -> str:
        return self._get("gemini", "model", DEFAULT_MODEL) or DEFAULT_MODEL

    @gemini_model.setter
    def gemini_model(self, value: str) -> None:
        self._set("gemini", "model", value)

    @property
    def proxy_url(self) -> str:
        return self._get("proxy", "url", DEFAULT_PROXY_URL) or DEFAULT_PROXY_URL

    @proxy_url.setter
    def proxy_url(self, value: str) -> None:
        self._set("proxy", "url", value)

    @property
    def proxy_port(self) -> int:
        try:
            return int(self._get("proxy", "port", "8000") or 8000)
        except ValueError:
            return 8000

    @proxy_port.setter
    def proxy_port(self, value: int) -> None:
        self._set("proxy", "port", str(int(value)))

    @property
    def auto_start_proxy(self) -> bool:
        return self._get("proxy", "auto_start", "true").lower() in ("1", "true", "yes", "on")

    @auto_start_proxy.setter
    def auto_start_proxy(self, value: bool) -> None:
        self._set("proxy", "auto_start", "true" if value else "false")

    @property
    def license_key(self) -> str:
        return self._get("license", "key")

    @license_key.setter
    def license_key(self, value: str) -> None:
        self._set("license", "key", (value or "").strip())

    # ------------------------------------------------------------------ tiện ích
    def effective_api_key(self) -> str:
        """Key dùng thật: config.ini trước, sau đó mới tới .env / biến môi trường."""
        return self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    def has_api_key(self) -> bool:
        return bool(self.effective_api_key())
