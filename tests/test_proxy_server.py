"""Test proxy dịch thuật: parse output và kiểm tra license."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

from server import proxy_server  # noqa: E402
from src.providers import classify_http_error  # noqa: E402


class TestParseNumbered:
    def test_parses_numbered_lines(self):
        raw = "1|Xin chào\n2|Tạm biệt"
        assert proxy_server._parse_numbered(raw, 2) == ["Xin chào", "Tạm biệt"]

    def test_tolerates_extra_whitespace(self):
        assert proxy_server._parse_numbered("  1 | Xin chào  ", 1) == ["Xin chào"]

    def test_missing_line_becomes_empty(self):
        assert proxy_server._parse_numbered("1|A\n3|C", 3) == ["A", "", "C"]

    def test_ignores_commentary_lines(self):
        raw = "Đây là bản dịch:\n1|A\n2|B\n(hết)"
        assert proxy_server._parse_numbered(raw, 2) == ["A", "B"]

    def test_keeps_pipe_inside_text(self):
        assert proxy_server._parse_numbered("1|a|b", 1) == ["a|b"]


class TestLicenseGate:
    def test_no_allowlist_accepts_everything(self, monkeypatch):
        monkeypatch.setattr(proxy_server, "ALLOWED_LICENSES", set())
        proxy_server._check_license(None)  # không ném lỗi

    def test_allowlist_rejects_unknown_key(self, monkeypatch):
        monkeypatch.setattr(proxy_server, "ALLOWED_LICENSES", {"good"})
        with pytest.raises(HTTPException) as exc:
            proxy_server._check_license("bad")
        assert exc.value.status_code == 403

    def test_allowlist_accepts_known_key(self, monkeypatch):
        monkeypatch.setattr(proxy_server, "ALLOWED_LICENSES", {"good"})
        proxy_server._check_license("good")


class TestHealth:
    def test_health_reports_model(self):
        body = proxy_server.health()
        assert body["status"] == "ok"
        assert "model" in body


class TestClassifyHttpError:
    """Phân loại lỗi giờ dùng chung cho cả 3 nhà cung cấp."""

    def test_401_is_bad_key(self):
        code, message = classify_http_error(401, "Unauthorized")
        assert code == "bad_key"
        assert "không hợp lệ" in message

    def test_403_is_bad_key(self):
        assert classify_http_error(403, "Forbidden")[0] == "bad_key"

    def test_gemini_api_key_invalid_body(self):
        assert classify_http_error(400, '{"error":{"status":"API_KEY_INVALID"}}')[0] == "bad_key"

    def test_openai_incorrect_key_body(self):
        assert classify_http_error(400, "Incorrect API key provided")[0] == "bad_key"

    def test_429_is_quota(self):
        code, message = classify_http_error(429, "Too Many Requests")
        assert code == "quota"
        assert "quota" in message.lower()

    def test_insufficient_quota_body(self):
        assert classify_http_error(400, '{"code":"insufficient_quota"}')[0] == "quota"

    def test_deepseek_insufficient_balance(self):
        assert classify_http_error(402, "Insufficient Balance")[0] == "quota"

    def test_404_is_bad_model(self):
        assert classify_http_error(404, "not found")[0] == "bad_model"

    def test_model_not_found_body(self):
        assert classify_http_error(400, '{"code":"model_not_found"}')[0] == "bad_model"

    def test_5xx_is_provider_down(self):
        code, message = classify_http_error(503, "Service Unavailable")
        assert code == "provider_down"
        assert "503" in message

    def test_unknown_keeps_body(self):
        code, message = classify_http_error(418, "chuyện lạ")
        assert code == "error"
        assert "chuyện lạ" in message


class TestHealthAndVerify:
    def test_no_key_reported(self, monkeypatch):
        monkeypatch.delenv("SUBAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert proxy_server.verify()["status"] == "no_key"

    def test_health_reflects_runtime_key(self, monkeypatch):
        monkeypatch.setenv("SUBAI_API_KEY", "abc")
        assert proxy_server.health()["api_key_configured"] is True

        monkeypatch.setenv("SUBAI_API_KEY", "")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert proxy_server.health()["api_key_configured"] is False

    def test_model_read_at_call_time(self, monkeypatch):
        monkeypatch.setenv("SUBAI_MODEL", "gemini-3-test")
        assert proxy_server.health()["model"] == "gemini-3-test"

    def test_provider_switching(self, monkeypatch):
        monkeypatch.delenv("SUBAI_MODEL", raising=False)
        monkeypatch.setenv("SUBAI_PROVIDER", "deepseek")
        body = proxy_server.health()
        assert body["provider"] == "deepseek"
        assert body["model"] == "deepseek-chat"
        assert body["provider_label"] == "DeepSeek"

    def test_unknown_provider_falls_back_to_gemini(self, monkeypatch):
        monkeypatch.setenv("SUBAI_PROVIDER", "khong-ton-tai")
        assert proxy_server.health()["provider"] == "gemini"

    def test_provider_specific_env_key_accepted(self, monkeypatch):
        monkeypatch.delenv("SUBAI_API_KEY", raising=False)
        monkeypatch.setenv("SUBAI_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert proxy_server.health()["api_key_configured"] is True

    def test_build_agent_matches_provider(self, monkeypatch):
        monkeypatch.setenv("SUBAI_PROVIDER", "openai")
        monkeypatch.setenv("SUBAI_API_KEY", "sk-test")
        monkeypatch.setenv("SUBAI_MODEL", "gpt-4o")

        agent = proxy_server.build_agent()
        assert agent.spec.name == "openai"
        assert agent.model == "gpt-4o"
        assert agent.api_key == "sk-test"
