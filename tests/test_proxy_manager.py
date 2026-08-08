"""Test bật/tắt server dịch thuật ngầm.

Các test có đánh dấu `integration` bật uvicorn thật nên cần fastapi + uvicorn.
"""

from __future__ import annotations

import sys

import pytest

from src.app_config import AppConfig
from src.proxy_manager import ProxyServerManager, probe_health
from src.utils import module_available

needs_server = pytest.mark.skipif(
    not (module_available("fastapi") and module_available("uvicorn")),
    reason="Cần fastapi và uvicorn",
)


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def manager(tmp_path):
    config = AppConfig.load(tmp_path / "config.ini")
    port = _free_port()
    config.proxy_port = port
    config.proxy_url = f"http://127.0.0.1:{port}"
    instance = ProxyServerManager(config)
    yield instance
    instance.stop()


class TestProbeHealth:
    def test_dead_port_returns_none(self):
        assert probe_health(f"http://127.0.0.1:{_free_port()}", timeout=1.0) is None

    def test_garbage_url_returns_none(self):
        assert probe_health("http://khong-ton-tai.invalid", timeout=1.0) is None


class TestLifecycle:
    def test_not_running_before_start(self, manager):
        assert not manager.is_running()

    def test_stop_is_safe_when_not_started(self, manager):
        manager.stop()
        manager.stop()

    def test_missing_dependencies_reported(self, manager, monkeypatch):
        monkeypatch.setattr("src.proxy_manager.module_available", lambda name: False)
        result = manager.start("key")
        assert not result.ok
        assert "fastapi" in result.message and "uvicorn" in result.message

    @needs_server
    def test_start_then_health_then_stop(self, manager):
        result = manager.start("test-key")
        assert result.ok, result.message
        assert manager.is_running()
        assert manager.is_healthy()

        manager.stop()
        assert not manager.is_running()
        assert not manager.is_healthy()

    @needs_server
    def test_api_key_reaches_the_server(self, manager):
        assert manager.start("test-key-123").ok
        health = probe_health(manager.url)
        assert health["api_key_configured"] is True

    @needs_server
    def test_empty_key_reported_as_not_configured(self, manager):
        assert manager.start("").ok
        assert probe_health(manager.url)["api_key_configured"] is False

    @needs_server
    def test_second_start_is_idempotent(self, manager):
        assert manager.start("key").ok
        first_pid = manager.process.pid

        second = manager.start("key")
        assert second.reused
        assert manager.process.pid == first_pid

    @needs_server
    def test_restart_picks_up_new_key(self, manager):
        assert manager.start("").ok
        assert probe_health(manager.url)["api_key_configured"] is False

        assert manager.restart("key-moi").ok
        assert probe_health(manager.url)["api_key_configured"] is True

    @needs_server
    def test_stop_kills_the_child_process(self, manager):
        manager.start("key")
        process = manager.process
        manager.stop()
        assert process.poll() is not None


class TestNoConsoleWindow:
    def test_windows_gets_no_window_flag(self, monkeypatch):
        from src import proxy_manager

        monkeypatch.setattr(proxy_manager.sys, "platform", "win32")
        assert proxy_manager._no_window_flags()["creationflags"] == 0x08000000

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="Chỉ kiểm trên POSIX")
    def test_posix_gets_no_extra_flags(self):
        from src import proxy_manager

        assert proxy_manager._no_window_flags() == {}


class TestDiagnose:
    """Kiểm tra client phân biệt đúng từng nguyên nhân hỏng."""

    def test_no_url(self):
        from src.translator import TranslatorClient

        status = TranslatorClient("").diagnose()
        assert status.code == "no_url"
        assert not status.ok

    def test_unreachable_proxy(self):
        from src.translator import TranslatorClient

        status = TranslatorClient(f"http://127.0.0.1:{_free_port()}").diagnose()
        assert status.code == "unreachable"
        assert "Không kết nối được" in status.message

    @needs_server
    def test_server_running_without_key(self, manager):
        from src.translator import TranslatorClient

        assert manager.start("").ok
        status = TranslatorClient(manager.url).diagnose()
        assert status.code == "no_key"
        assert "chưa có API key" in status.message

    @needs_server
    def test_bad_key_detected_through_the_stack(self, manager):
        """Key rác: nếu có google-genai thì báo bad_key, không thì báo thiếu thư viện."""
        from src.translator import TranslatorClient

        assert manager.start("key-rac-khong-ton-tai").ok
        status = TranslatorClient(manager.url).diagnose()
        assert not status.ok
        assert status.code in ("bad_key", "network", "error")
