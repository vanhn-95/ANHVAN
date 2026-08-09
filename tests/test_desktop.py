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
    def test_opens_with_five_tabs(self, window):
        assert window.tabs.count() == 5
        assert window.tabs.tabText(0) == "Xử lý video"
        assert "Affiliate Bot" in window.tabs.tabText(1)

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


class TestProviderUi:
    def test_combo_lists_all_providers(self, window):
        from src.providers import PROVIDERS

        names = {window.provider_combo.itemData(i)
                 for i in range(window.provider_combo.count())}
        assert names == set(PROVIDERS)

    def test_switching_provider_loads_its_defaults(self, window):
        window._select_data(window.provider_combo, "openai")
        assert window.current_provider() == "openai"
        assert window.model_input.currentText() == "gpt-4o"
        assert "platform.openai.com" in window.key_hint.text()

        window._select_data(window.provider_combo, "deepseek")
        assert window.model_input.currentText() == "deepseek-chat"
        assert "deepseek.com" in window.key_hint.text()

    def test_each_provider_keeps_its_own_key(self, window, tmp_path):
        window.app_config.path = tmp_path / "config.ini"

        window._select_data(window.provider_combo, "openai")
        window.api_key_input.setText("sk-openai-key")

        window._select_data(window.provider_combo, "deepseek")
        assert window.api_key_input.text() == ""      # không lẫn key của nhau
        window.api_key_input.setText("sk-deepseek-key")

        window._select_data(window.provider_combo, "openai")
        assert window.api_key_input.text() == "sk-openai-key"

        window.save_app_config()
        from src.app_config import AppConfig

        saved = AppConfig.load(tmp_path / "config.ini")
        assert saved.api_key_for("openai") == "sk-openai-key"
        assert saved.api_key_for("deepseek") == "sk-deepseek-key"

    def test_custom_model_is_saved(self, window, tmp_path):
        window.app_config.path = tmp_path / "config.ini"
        window._select_data(window.provider_combo, "openai")
        window.model_input.setCurrentText("gpt-4.1-mini")
        window.save_app_config()

        from src.app_config import AppConfig

        assert AppConfig.load(tmp_path / "config.ini").model_for("openai") == "gpt-4.1-mini"

    def test_provider_persists_across_restart(self, app, tmp_path, monkeypatch):
        from src.app_config import AppConfig

        config = AppConfig.load(tmp_path / "config.ini")
        config.provider = "deepseek"
        config.set_api_key_for("deepseek", "sk-ds")
        config.set_model_for("deepseek", "deepseek-reasoner")
        config.save()

        monkeypatch.setattr("src.config.SETTINGS_FILE", tmp_path / "settings.json")
        monkeypatch.setattr("src.app_config.CONFIG_FILE", tmp_path / "config.ini")

        fresh = MainWindow()
        try:
            assert fresh.current_provider() == "deepseek"
            assert fresh.api_key_input.text() == "sk-ds"
            assert fresh.model_input.currentText() == "deepseek-reasoner"
        finally:
            fresh.deleteLater()

    def test_model_combo_is_editable(self, window):
        assert window.model_input.isEditable()


class TestConnectionDialog:
    def test_success_shows_information_dialog(self, window, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        from src.translator import ProxyStatus

        shown = {}
        monkeypatch.setattr(
            QMessageBox, "information",
            lambda parent, title, text, *a, **k: shown.update(title=title, text=text),
        )
        window._show_proxy_dialog(ProxyStatus(True, "ok", "Kết nối tốt."))
        assert shown["title"] == "Kết nối thành công"
        assert "Kết nối tốt." in shown["text"]

    @pytest.mark.parametrize("code,title", [
        ("bad_key", "API key sai"),
        ("unreachable", "Proxy chưa chạy"),
        ("network", "Mất mạng"),
        ("quota", "Hết hạn mức"),
        ("bad_model", "Sai tên model"),
        ("no_key", "Chưa có API key"),
    ])
    def test_failure_titles(self, window, monkeypatch, code, title):
        from PySide6.QtWidgets import QMessageBox
        from src.translator import ProxyStatus

        captured = {}
        monkeypatch.setattr(QMessageBox, "exec", lambda self: captured.update(
            title=self.windowTitle(), text=self.text(), detail=self.detailedText()
        ))
        window._show_proxy_dialog(ProxyStatus(False, code, "Có lỗi.", "Gợi ý sửa."))
        assert captured["title"] == title
        assert "Có lỗi." in captured["text"]
        assert code in captured["detail"]

    def test_dialog_not_shown_when_only_updating_status(self, window, monkeypatch):
        """_on_proxy_checked chỉ cập nhật nhãn - hộp thoại modal sẽ treo test."""
        from PySide6.QtWidgets import QMessageBox
        from src.translator import ProxyStatus

        calls = []
        monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(1))
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(1))

        window._on_proxy_checked(ProxyStatus(False, "bad_key", "Sai key."))
        assert calls == []
        assert "Sai key." in window.proxy_status.text()

    def test_key_label_follows_provider(self, window):
        window._select_data(window.provider_combo, "openai")
        assert "OpenAI" in window.api_key_label.text()
        assert "OPENAI_API_KEY" in window.api_key_input.placeholderText()

        window._select_data(window.provider_combo, "gemini")
        assert "Gemini" in window.api_key_label.text()


class TestCreatorTab:
    def test_tab_exists_with_controls(self, window):
        tab = window.creator_tab
        assert tab.start_btn.text().endswith("Bắt đầu chạy Bot")
        assert tab.cancel_btn.text() == "Dừng"
        assert not tab.cancel_btn.isEnabled()

    def test_all_feature_toggles_present(self, window):
        tab = window.creator_tab
        for checkbox in (tab.chk_rewrite, tab.chk_tts, tab.chk_keep_sub,
                         tab.chk_intro, tab.chk_intro_ai, tab.chk_music,
                         tab.chk_ducking, tab.chk_separate, tab.chk_clone):
            assert checkbox is not None

    def test_collect_config_reads_form(self, window):
        tab = window.creator_tab
        tab.source_input.setText("https://v.douyin.com/abc")
        tab.intro_input.setText("MẸO HAY MỖI NGÀY")
        tab.music_db.setValue(-12.0)

        config = tab.collect_config()
        assert config.source == "https://v.douyin.com/abc"
        assert config.intro_text == "MẸO HAY MỖI NGÀY"
        assert config.music_db == -12.0

    def test_disabling_intro_disables_its_fields(self, window):
        tab = window.creator_tab
        tab.chk_intro.setChecked(False)
        assert not tab.intro_input.isEnabled()
        assert not tab.chk_intro_ai.isEnabled()

        tab.chk_intro.setChecked(True)
        assert tab.intro_input.isEnabled()

    def test_disabling_tts_disables_voice_clone(self, window):
        tab = window.creator_tab
        tab.chk_tts.setChecked(True)
        tab.chk_clone.setChecked(True)
        tab.chk_tts.setChecked(False)
        assert not tab.chk_clone.isChecked()
        assert not tab.chk_clone.isEnabled()

    def test_plan_label_follows_toggles(self, window):
        tab = window.creator_tab
        tab.chk_intro.setChecked(True)
        assert "intro 3 giây" in tab.plan_label.text().lower()

        tab.chk_intro.setChecked(False)
        assert "intro 3 giây" not in tab.plan_label.text().lower()

    def test_invalid_config_blocks_start(self, window, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        window.creator_tab.source_input.setText("")
        window.creator_tab.start()

        assert warned
        assert window.creator_tab.worker is None

    def test_only_one_job_at_a_time(self, window, monkeypatch):
        """Bot không được chạy khi pipeline thường đang chạy."""
        from PySide6.QtWidgets import QMessageBox

        class FakeWorker:
            def isRunning(self):
                return True

        warned = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        window.worker = FakeWorker()
        try:
            assert window.claim_job(window.creator_tab) is False
            assert warned
        finally:
            window.worker = None

    def test_provider_combo_defaults_to_saved(self, window):
        assert window.creator_tab.provider_combo.currentData() == window.app_config.provider

    def test_host_progress_bridge(self, window):
        window.set_progress(0.5)
        assert window.progress_bar.value() == 500

        window.set_stage("Tạo intro", 8, 9)
        assert "8/9" in window.stage_label.text()


class TestPreviewAndTimeline:
    def test_splitter_has_two_panes(self, window):
        assert window.creator_tab.splitter.count() == 2

    def test_preview_starts_empty(self, window):
        preview = window.creator_tab.preview
        assert preview.info is None
        assert preview.duration == 0.0

    def test_url_source_explains_no_preview(self, window):
        preview = window.creator_tab.preview
        preview.load("https://v.douyin.com/abc")
        assert "đường link" in preview.image.text()

    def test_empty_source_message(self, window):
        window.creator_tab.preview.load("")
        assert "Chưa nhập" in window.creator_tab.preview.image.text()

    def test_timeline_has_three_tracks(self, window):
        names = [track.name for track in window.creator_tab.timeline.tracks]
        assert names == ["Video", "Giọng nói", "Nhạc nền"]

    def test_timeline_reflects_enabled_steps(self, window):
        timeline = window.creator_tab.timeline
        timeline.set_layout(30.0, has_intro=True, has_voice=True, has_music=True)
        labels = timeline.clip_labels()
        assert "Intro 3s" in labels
        assert "Video gốc" in labels
        assert "Giọng đọc mới (TTS)" in labels
        assert "Nhạc nền mới" in labels

    def test_timeline_drops_disabled_tracks(self, window):
        timeline = window.creator_tab.timeline
        timeline.set_layout(30.0, has_intro=False, has_voice=False, has_music=True)
        labels = timeline.clip_labels()
        assert "Intro 3s" not in labels
        assert "Giọng đọc mới (TTS)" not in labels
        assert "Nhạc nền mới" in labels

    def test_intro_extends_total_duration(self, window):
        timeline = window.creator_tab.timeline
        timeline.set_layout(30.0, has_intro=True)
        assert timeline.total_duration == pytest.approx(33.0)

    def test_body_clip_starts_after_intro(self, window):
        timeline = window.creator_tab.timeline
        timeline.set_layout(20.0, has_intro=True, has_voice=True)
        voice = timeline.tracks[1].clips[0]
        assert voice.start == pytest.approx(3.0)
        assert voice.end == pytest.approx(23.0)

    def test_toggling_checkbox_updates_timeline(self, window):
        tab = window.creator_tab
        tab.preview.duration = 40.0
        tab.chk_music.setChecked(False)
        assert "Nhạc nền mới" not in tab.timeline.clip_labels()

        tab.chk_music.setChecked(True)
        assert "Nhạc nền mới" in tab.timeline.clip_labels()


class TestExportSettings:
    def test_defaults_are_tiktok_ready(self, window):
        config = window.creator_tab.collect_config()
        assert (config.output_width, config.output_height) == (1080, 1920)
        assert config.crf == 18
        assert config.preset == "slow"
        assert config.audio_bitrate == "192k"
        assert config.strip_metadata is True
        assert config.fill_mode == "blur"

    def test_resolution_choice_flows_to_config(self, window):
        tab = window.creator_tab
        tab.resolution_combo.setCurrentIndex(1)      # 720x1280
        config = tab.collect_config()
        assert (config.output_width, config.output_height) == (720, 1280)

    def test_quality_controls_flow_to_config(self, window):
        tab = window.creator_tab
        tab.crf_spin.setValue(23)
        tab.preset_combo.setCurrentText("medium")
        tab.audio_bitrate_combo.setCurrentText("320k")
        tab.chk_strip_metadata.setChecked(False)

        config = tab.collect_config()
        assert config.crf == 23
        assert config.preset == "medium"
        assert config.audio_bitrate == "320k"
        assert config.strip_metadata is False

    def test_test_button_renamed(self, window):
        assert "AI" in window.test_btn.text() and "Proxy" in window.test_btn.text()


class TestCpuOnlyMachine:
    """Máy AMD/Intel không có NVIDIA: tuyệt đối không được gợi ý bản cu121."""

    @pytest.fixture
    def cpu_only(self, monkeypatch):
        from desktop import environment

        monkeypatch.setattr(environment, "has_nvidia_gpu", lambda: False)
        return environment

    @pytest.fixture
    def with_nvidia(self, monkeypatch):
        from desktop import environment

        monkeypatch.setattr(environment, "has_nvidia_gpu", lambda: True)
        return environment

    def test_no_cuda_command_anywhere_on_cpu(self, cpu_only):
        for check in cpu_only.run_checks():
            assert "cu121" not in check.fix
            assert "download.pytorch.org" not in check.fix

    def test_cpu_message_matches_request(self, cpu_only):
        gpu = next(c for c in cpu_only.run_checks() if c.name == "GPU / CUDA")
        assert gpu.detail == "Đang chạy chế độ CPU (sẽ chậm hơn). Để tối ưu, cần có GPU NVIDIA."
        assert gpu.fix == ""
        assert not gpu.required

    def test_torch_hint_is_plain_pip_on_cpu(self, cpu_only):
        assert cpu_only.torch_install_command() == "pip install torch torchaudio"

    def test_torch_hint_is_cuda_when_nvidia_present(self, with_nvidia):
        assert "cu121" in with_nvidia.torch_install_command()

    def test_gpu_check_never_blocks(self, cpu_only):
        blocking = [c.name for c in cpu_only.blocking_problems(cpu_only.run_checks())]
        assert "GPU / CUDA" not in blocking
        assert "PyTorch" not in blocking

    def test_faster_whisper_is_the_blocking_one(self, cpu_only):
        """Faster-Whisper dùng CTranslate2, không cần torch - nên nó mới là bắt buộc."""
        whisper = next(c for c in cpu_only.run_checks() if c.name == "Faster-Whisper")
        assert whisper.required
        assert whisper.fix == "pip install faster-whisper"

    def test_missing_popup_spells_out_install_command(self, cpu_only):
        checks = [
            cpu_only.Check("Faster-Whisper", False, "Thiếu", True, "pip install faster-whisper")
        ]
        text = cpu_only.format_missing(checks)
        assert "Lệnh cài đặt: pip install faster-whisper" in text
        assert "cu121" not in text

    def test_nvidia_detection_uses_nvidia_smi(self, monkeypatch):
        from desktop import environment

        monkeypatch.setattr(environment.shutil, "which", lambda name: None)
        assert environment.has_nvidia_gpu() is False


class TestProviderModelLists:
    def test_gemini_models_available(self, window):
        window._select_data(window.provider_combo, "gemini")
        models = [window.model_input.itemText(i) for i in range(window.model_input.count())]
        for name in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"):
            assert name in models

    def test_openai_models_available(self, window):
        window._select_data(window.provider_combo, "openai")
        models = [window.model_input.itemText(i) for i in range(window.model_input.count())]
        for name in ("gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"):
            assert name in models

    def test_deepseek_models_available(self, window):
        window._select_data(window.provider_combo, "deepseek")
        models = [window.model_input.itemText(i) for i in range(window.model_input.count())]
        for name in ("deepseek-v3", "deepseek-r1", "deepseek-chat"):
            assert name in models

    def test_provider_hint_lists_all_three(self, window):
        # Nhãn gợi ý nằm ngay dưới combo, cho người dùng biết bấm vào đổi được.
        from PySide6.QtWidgets import QLabel

        texts = [w.text() for w in window.findChildren(QLabel) if "Bấm vào ô trên" in w.text()]
        assert texts, "thiếu dòng gợi ý dưới dropdown"
        assert "Google Gemini" in texts[0]
        assert "ChatGPT (OpenAI)" in texts[0]
        assert "DeepSeek" in texts[0]

    def test_combo_arrow_not_styled_away(self):
        """Đặt luật lên drop-down/down-arrow làm mũi tên biến mất trong Fusion.

        Chỉ bắt lỗi khi có LUẬT thật (selector kèm dấu `{`), chú thích nhắc tên
        hai phần tử này thì không sao.
        """
        import re

        from desktop.theme import STYLESHEET

        for selector in ("drop-down", "down-arrow"):
            rule = re.search(r"QComboBox::" + selector + r"[^\n]*\{", STYLESHEET)
            assert rule is None, f"stylesheet đang style ::{selector}, mũi tên sẽ mất"
