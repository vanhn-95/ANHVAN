"""Test loader .env."""

from __future__ import annotations

import os

from src.env_file import load_dotenv, parse_env


class TestParseEnv:
    def test_basic_pairs(self):
        assert parse_env("A=1\nB=2") == {"A": "1", "B": "2"}

    def test_strips_quotes(self):
        assert parse_env('KEY="giá trị"') == {"KEY": "giá trị"}
        assert parse_env("KEY='abc'") == {"KEY": "abc"}

    def test_ignores_comments_and_blanks(self):
        assert parse_env("# ghi chú\n\nA=1\n") == {"A": "1"}

    def test_supports_export_prefix(self):
        assert parse_env("export GEMINI_API_KEY=abc") == {"GEMINI_API_KEY": "abc"}

    def test_keeps_equals_inside_value(self):
        assert parse_env("TOKEN=a=b=c") == {"TOKEN": "a=b=c"}

    def test_empty_value_allowed(self):
        assert parse_env('EMPTY=""') == {"EMPTY": ""}


class TestLoadDotenv:
    def test_loads_into_environ(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('SUBAI_TEST_KEY="xin chào"\n', encoding="utf-8")
        monkeypatch.delenv("SUBAI_TEST_KEY", raising=False)

        load_dotenv(env)
        assert os.environ["SUBAI_TEST_KEY"] == "xin chào"
        monkeypatch.delenv("SUBAI_TEST_KEY", raising=False)

    def test_existing_environ_wins_by_default(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("SUBAI_TEST_KEY=from_file", encoding="utf-8")
        monkeypatch.setenv("SUBAI_TEST_KEY", "from_shell")

        load_dotenv(env)
        assert os.environ["SUBAI_TEST_KEY"] == "from_shell"

    def test_override_flag_replaces_environ(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("SUBAI_TEST_KEY=from_file", encoding="utf-8")
        monkeypatch.setenv("SUBAI_TEST_KEY", "from_shell")

        load_dotenv(env, override=True)
        assert os.environ["SUBAI_TEST_KEY"] == "from_file"

    def test_missing_file_is_not_an_error(self, tmp_path):
        assert load_dotenv(tmp_path / "khong-co.env") == {}


class TestConfigReadsEnv:
    def test_proxy_url_default_from_env(self, monkeypatch):
        from src.config import JobConfig

        monkeypatch.setenv("SUBAI_PROXY_URL", "http://10.0.0.5:9000")
        assert JobConfig().proxy_url == "http://10.0.0.5:9000"

    def test_proxy_url_falls_back_to_localhost(self, monkeypatch):
        from src.config import JobConfig

        monkeypatch.delenv("SUBAI_PROXY_URL", raising=False)
        assert JobConfig().proxy_url == "http://127.0.0.1:8000"
