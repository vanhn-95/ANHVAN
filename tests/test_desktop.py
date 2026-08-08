"""Smoke test giao diện: chạy headless bằng QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from desktop.app import create_app  # noqa: E402
from desktop.environment import blocking_problems, run_checks  # noqa: E402
from desktop.main_window import MainWindow  # noqa: E402
from src.config import JobConfig  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_app([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    # Trỏ mọi file cấu hình vào tmp_path để test không đụng config thật của máy.
    monkeypatch.setattr("src.config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("src.app_config.CONFIG_FILE", tmp_path / "config.ini")
    win = MainWindow()
    yield win
    win.deleteLater()


class TestMainWindow:
    def test_opens_with_four_tabs(self, window):
        assert window.tabs.count() == 4
        assert window.tabs.tabText(0) == "Xử lý video"

    def test_collect_config_reads_form(self, window):
        window.source_input.setText("https://youtu.be/abc")
        window.output_input.setText("/tmp/subai")
        window.model_combo.setCurrentText("small")

        config = window.collect_config()
        assert config.source == "https://youtu.be/abc"
        assert config.output_dir == "/tmp/subai"
        assert config.whisper_model == "small"

    def test_form_roundtrip(self, window):
        original = JobConfig(
            source="a.mp4", output_dir="/tmp/o", target_lang="en", whisper_model="large-v3",
            device="cpu", separate_audio=False, burn_subtitles=True, max_speed_ratio=1.2,
        )
        window._apply_config(original)
        assert window.collect_config() == original

    def test_disabling_translation_disables_dubbing(self, window):
        window.chk_translate.setChecked(True)
        window.chk_dubbing.setChecked(True)
        window.chk_translate.setChecked(False)
        assert not window.chk_dubbing.isChecked()
        assert not window.chk_dubbing.isEnabled()

    def test_plan_label_follows_options(self, window):
        window.chk_translate.setChecked(True)
        window.chk_dubbing.setChecked(True)
        assert "Lồng tiếng AI" in window.plan_label.text()

        window.chk_dubbing.setChecked(False)
        assert "Lồng tiếng AI" not in window.plan_label.text()

    def test_invalid_config_does_not_start_worker(self, window, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        window.source_input.setText("")
        window._start()
        assert warned
        assert window.worker is None

    def test_license_tab_shows_hwid(self, window):
        assert len(window.hwid_field.text()) >= 8
        assert window.hwid_field.isReadOnly()

    def test_log_appends(self, window):
        window._append_log("dòng test")
        assert "dòng test" in window.log_view.toPlainText()

    def test_stage_label_updates(self, window):
        window._on_stage("Trích xuất phụ đề", 3, 6)
        assert "3/6" in window.stage_label.text()


class TestEnvironmentChecks:
    def test_checks_return_entries(self):
        checks = run_checks()
        names = {c.name for c in checks}
        assert {"Python", "FFmpeg", "GPU / CUDA"} <= names

    def test_python_check_always_ok(self):
        python = next(c for c in run_checks() if c.name == "Python")
        assert python.ok

    def test_blocking_problems_only_required(self):
        for check in blocking_problems(run_checks()):
            assert check.required and not check.ok

    def test_rubberband_is_optional(self):
        rubberband = next(c for c in run_checks() if c.name == "Rubber Band")
        assert not rubberband.required

    def test_rubberband_needs_module_and_binary(self, monkeypatch):
        from desktop import environment

        monkeypatch.setattr(environment, "module_available", lambda name: True)
        monkeypatch.setattr(environment.shutil, "which", lambda name: None)

        check = environment._rubberband_check()
        assert not check.ok
        assert "binary" in check.detail
        assert "atempo" in check.detail


class TestApiKeyUi:
    def test_api_key_hidden_by_default(self, window):
        from PySide6.QtWidgets import QLineEdit

        assert window.api_key_input.echoMode() == QLineEdit.Password

    def test_show_button_reveals_key(self, window):
        from PySide6.QtWidgets import QLineEdit

        window.show_key_btn.setChecked(True)
        assert window.api_key_input.echoMode() == QLineEdit.Normal
        assert window.show_key_btn.text() == "Ẩn"

        window.show_key_btn.setChecked(False)
        assert window.api_key_input.echoMode() == QLineEdit.Password

    def test_saving_writes_config_ini(self, window, tmp_path):
        window.app_config.path = tmp_path / "config.ini"
        window.api_key_input.setText("AIza-key-test")
        window.proxy_input.setText("http://127.0.0.1:8123")

        path = window.save_app_config()
        assert path.exists()

        from src.app_config import AppConfig

        reloaded = AppConfig.load(path)
        assert reloaded.gemini_api_key == "AIza-key-test"
        assert reloaded.proxy_url == "http://127.0.0.1:8123"

    def test_config_ini_populates_fields_on_open(self, app, tmp_path, monkeypatch):
        """Key đã lưu phải tự điền lại ở lần mở app sau."""
        from src.app_config import AppConfig

        config = AppConfig.load(tmp_path / "config.ini")
        config.gemini_api_key = "key-da-luu"
        config.proxy_url = "http://10.1.2.3:8000"
        config.save()

        monkeypatch.setattr("src.config.SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr("src.app_config.CONFIG_FILE", tmp_path / "config.ini")

        fresh = MainWindow()
        try:
            assert fresh.api_key_input.text() == "key-da-luu"
            assert fresh.proxy_input.text() == "http://10.1.2.3:8000"
        finally:
            fresh.deleteLater()

    def test_empty_proxy_url_blocks_check(self, window):
        window.proxy_input.setText("")
        window._test_proxy()
        assert "Chưa nhập địa chỉ" in window.proxy_status.text()
        assert window.proxy_worker is None

    def test_status_rendering_for_failure(self, window):
        from src.translator import ProxyStatus

        window._on_proxy_checked(ProxyStatus(False, "bad_key", "Key sai.", "Lấy key mới."))
        text = window.proxy_status.text()
        assert "Key sai." in text and "Lấy key mới." in text

    def test_status_rendering_for_success(self, window):
        from src.translator import ProxyStatus

        window._on_proxy_checked(ProxyStatus(True, "ok", "Kết nối tốt."))
        assert "Kết nối tốt." in window.proxy_status.text()

    def test_server_status_shows_stopped(self, window):
        from src.proxy_manager import ProxyServerManager

        ProxyServerManager.instance().stop()
        window._refresh_server_status()
        assert "Đã tắt" in window.server_status.text()
        assert window.server_toggle_btn.text() == "Bật server"
