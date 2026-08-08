"""Cấu hình job và cấu hình ứng dụng (persist ra đĩa)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

APP_NAME = "SubAI Studio"
APP_DIR = Path(os.environ.get("SUBAI_HOME", Path.home() / ".subai"))
SETTINGS_FILE = APP_DIR / "settings.json"

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
DEVICES = ["auto", "cuda", "cpu"]
COMPUTE_TYPES = ["auto", "float16", "int8_float16", "int8", "float32"]

LANGUAGES: Dict[str, str] = {
    "auto": "Tự động nhận diện",
    "vi": "Tiếng Việt",
    "en": "English",
    "zh": "中文 (Trung)",
    "ja": "日本語 (Nhật)",
    "ko": "한국어 (Hàn)",
    "th": "ไทย (Thái)",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "ru": "Русский",
}

# Ngôn ngữ đích không bao giờ là "auto".
TARGET_LANGUAGES = {k: v for k, v in LANGUAGES.items() if k != "auto"}


@dataclass
class JobConfig:
    """Toàn bộ thông số của một lần chạy pipeline."""

    source: str = ""                 # URL hoặc đường dẫn file local
    output_dir: str = field(
        default_factory=lambda: os.environ.get(
            "SUBAI_OUTPUT_DIR", str(Path.home() / "SubAI" / "output")
        )
    )
    source_lang: str = "auto"
    target_lang: str = "vi"

    # ASR
    whisper_model: str = "medium"
    device: str = "auto"
    compute_type: str = "auto"
    vad_filter: bool = True

    # Tách nhạc nền
    separate_audio: bool = True
    demucs_model: str = "htdemucs"

    # Dịch (mặc định lấy từ .env nếu có, xem .env.example)
    translate: bool = True
    proxy_url: str = field(
        default_factory=lambda: os.environ.get("SUBAI_PROXY_URL", "http://127.0.0.1:8000")
    )
    license_key: str = field(default_factory=lambda: os.environ.get("SUBAI_LICENSE_KEY", ""))

    # Lồng tiếng
    dubbing: bool = True
    voice_clone: bool = True
    tts_speaker_wav: str = ""        # để trống = tự trích giọng mẫu từ vocal gốc
    max_speed_ratio: float = 1.35    # giới hạn time-stretch để giọng không bị méo

    # Render
    burn_subtitles: bool = False
    auto_ducking: bool = True
    ducking_db: float = -12.0
    keep_intermediates: bool = False

    def validate(self) -> None:
        """Ném ValueError với thông điệp tiếng Việt nếu cấu hình không hợp lệ."""
        if not self.source.strip():
            raise ValueError("Chưa nhập nguồn video (URL hoặc file).")
        if not self.output_dir.strip():
            raise ValueError("Chưa chọn thư mục xuất kết quả.")
        if self.target_lang not in TARGET_LANGUAGES:
            raise ValueError(f"Ngôn ngữ đích không hợp lệ: {self.target_lang}")
        if self.source_lang not in LANGUAGES:
            raise ValueError(f"Ngôn ngữ nguồn không hợp lệ: {self.source_lang}")
        if self.whisper_model not in WHISPER_MODELS:
            raise ValueError(f"Model Whisper không hợp lệ: {self.whisper_model}")
        if self.translate and not self.proxy_url.strip():
            raise ValueError("Bật dịch thuật thì phải có địa chỉ Proxy Server.")
        if not 1.0 <= self.max_speed_ratio <= 2.0:
            raise ValueError("Tỉ lệ tăng tốc giọng đọc phải nằm trong khoảng 1.0 - 2.0.")
        if self.dubbing and not self.translate:
            raise ValueError("Lồng tiếng cần bật dịch thuật để có lời thoại đích.")
        if self.tts_speaker_wav and not Path(self.tts_speaker_wav).is_file():
            raise ValueError(f"Không tìm thấy file giọng mẫu: {self.tts_speaker_wav}")

    def is_url(self) -> bool:
        return self.source.strip().lower().startswith(("http://", "https://"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AppSettings:
    """Trạng thái ứng dụng được ghi nhớ giữa các phiên."""

    last_job: JobConfig = field(default_factory=JobConfig)
    recent_sources: list = field(default_factory=list)
    window_geometry: str = ""

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "AppSettings":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        settings = cls()
        settings.last_job = JobConfig.from_dict(raw.get("last_job", {}))
        settings.recent_sources = [str(s) for s in raw.get("recent_sources", [])][:10]
        settings.window_geometry = str(raw.get("window_geometry", ""))
        return settings

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_job": self.last_job.to_dict(),
            "recent_sources": self.recent_sources[:10],
            "window_geometry": self.window_geometry,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def remember_source(self, source: str) -> None:
        source = source.strip()
        if not source:
            return
        if source in self.recent_sources:
            self.recent_sources.remove(source)
        self.recent_sources.insert(0, source)
        del self.recent_sources[10:]
