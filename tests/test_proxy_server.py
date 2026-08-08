"""Test proxy dịch thuật: parse output và kiểm tra license."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402

from server import proxy_server  # noqa: E402


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
