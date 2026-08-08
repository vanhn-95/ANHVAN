"""Test lưu/đọc config.ini."""

from __future__ import annotations

import os
import stat

import pytest

from src.app_config import DEFAULT_MODEL, DEFAULT_PROXY_URL, AppConfig


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.ini"


class TestDefaults:
    def test_fresh_config_has_sensible_defaults(self, config_path):
        config = AppConfig.load(config_path)
        assert config.gemini_api_key == ""
        assert config.gemini_model == DEFAULT_MODEL
        assert config.proxy_url == DEFAULT_PROXY_URL
        assert config.proxy_port == 8000
        assert config.auto_start_proxy is True

    def test_missing_file_does_not_raise(self, tmp_path):
        AppConfig.load(tmp_path / "khong-co.ini")

    def test_corrupt_file_falls_back_to_defaults(self, config_path):
        config_path.write_text("đây không phải ini !!!", encoding="utf-8")
        assert AppConfig.load(config_path).proxy_url == DEFAULT_PROXY_URL


class TestRoundtrip:
    def test_api_key_survives_save_and_load(self, config_path):
        config = AppConfig.load(config_path)
        config.gemini_api_key = "AIza-test-key-123"
        config.save()

        assert AppConfig.load(config_path).gemini_api_key == "AIza-test-key-123"

    def test_all_fields_roundtrip(self, config_path):
        config = AppConfig.load(config_path)
        config.gemini_api_key = "key"
        config.gemini_model = "gemini-2.0-pro"
        config.proxy_url = "http://10.0.0.9:9100"
        config.proxy_port = 9100
        config.auto_start_proxy = False
        config.license_key = "lic-abc"
        config.save()

        loaded = AppConfig.load(config_path)
        assert loaded.gemini_api_key == "key"
        assert loaded.gemini_model == "gemini-2.0-pro"
        assert loaded.proxy_url == "http://10.0.0.9:9100"
        assert loaded.proxy_port == 9100
        assert loaded.auto_start_proxy is False
        assert loaded.license_key == "lic-abc"

    def test_key_is_trimmed(self, config_path):
        config = AppConfig.load(config_path)
        config.gemini_api_key = "  key-co-khoang-trang  "
        assert config.gemini_api_key == "key-co-khoang-trang"

    def test_saved_file_warns_about_secret(self, config_path):
        config = AppConfig.load(config_path)
        config.gemini_api_key = "secret"
        content = config.save().read_text(encoding="utf-8")
        assert "API KEY" in content

    @pytest.mark.skipif(os.name == "nt", reason="Windows không có chmod POSIX")
    def test_saved_file_is_owner_only(self, config_path):
        config = AppConfig.load(config_path)
        config.gemini_api_key = "secret"
        path = config.save()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestPrecedence:
    def test_config_wins_over_environment(self, config_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "tu-env")
        config = AppConfig.load(config_path)
        config.gemini_api_key = "tu-config"
        assert config.effective_api_key() == "tu-config"

    def test_falls_back_to_environment(self, config_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "tu-env")
        assert AppConfig.load(config_path).effective_api_key() == "tu-env"

    def test_no_key_anywhere(self, config_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        config = AppConfig.load(config_path)
        assert config.effective_api_key() == ""
        assert not config.has_api_key()


class TestAutoStartParsing:
    @pytest.mark.parametrize("value,expected", [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("0", False), ("no", False), ("linh tinh", False),
    ])
    def test_boolean_values(self, config_path, value, expected):
        config_path.write_text(f"[proxy]\nauto_start = {value}\n", encoding="utf-8")
        assert AppConfig.load(config_path).auto_start_proxy is expected

    def test_invalid_port_falls_back(self, config_path):
        config_path.write_text("[proxy]\nport = khong-phai-so\n", encoding="utf-8")
        assert AppConfig.load(config_path).proxy_port == 8000
