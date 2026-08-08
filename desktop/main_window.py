"""Cửa sổ chính của SubAI Studio."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

# Cho phép chạy trực tiếp `python desktop/main_window.py` (không qua package).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import (
    APP_NAME,
    COMPUTE_TYPES,
    DEVICES,
    LANGUAGES,
    TARGET_LANGUAGES,
    WHISPER_MODELS,
    AppSettings,
    JobConfig,
)
from src.main_pipeline import PipelineResult, plan_stages
from src.security_guard import get_hwid, verify_license
from src.translator import TranslatorClient

from desktop.environment import blocking_problems, run_checks
from desktop.theme import DANGER, OK, WARN
from desktop.worker import PipelineWorker

VIDEO_FILTER = "Video (*.mp4 *.mkv *.mov *.avi *.webm *.flv);;Tất cả file (*)"


def _scrollable(page: QWidget) -> QScrollArea:
    """Bọc tab trong vùng cuộn để cửa sổ nhỏ không bóp méo các hàng nhập liệu."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.worker: Optional[PipelineWorker] = None
        self.last_result: Optional[PipelineResult] = None

        self.setWindowTitle(f"{APP_NAME} - Lồng tiếng & phụ đề AI")
        self.setMinimumSize(1000, 720)
        self.resize(1180, 900)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(_scrollable(self._build_job_tab()), "Xử lý video")
        self.tabs.addTab(_scrollable(self._build_advanced_tab()), "Tuỳ chỉnh nâng cao")
        self.tabs.addTab(self._build_environment_tab(), "Môi trường")
        self.tabs.addTab(_scrollable(self._build_license_tab()), "Bản quyền")
        layout.addWidget(self.tabs, stretch=1)

        layout.addWidget(self._build_progress_panel())
        self.setCentralWidget(root)

        self._apply_config(self.settings.last_job)
        self._refresh_environment()
        self._refresh_license()

    # ------------------------------------------------------------- xây dựng UI
    def _build_header(self) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)

        text = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel("Tải video → tách nhạc nền → phụ đề AI → dịch → lồng tiếng → render")
        subtitle.setObjectName("subtitle")
        text.addWidget(title)
        text.addWidget(subtitle)
        row.addLayout(text)
        row.addStretch(1)

        self.header_status = QLabel("Đang kiểm tra môi trường...")
        self.header_status.setObjectName("subtitle")
        self.header_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.header_status)
        return header

    def _build_job_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        # --- Nguồn ---
        source_box = QGroupBox("Nguồn video")
        source_layout = QGridLayout(source_box)
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("Dán URL (YouTube, TikTok, Bilibili...) hoặc chọn file")
        browse = QPushButton("Chọn file...")
        browse.clicked.connect(self._pick_source_file)
        source_layout.addWidget(QLabel("Video"), 0, 0)
        source_layout.addWidget(self.source_input, 0, 1)
        source_layout.addWidget(browse, 0, 2)

        self.output_input = QLineEdit()
        pick_out = QPushButton("Chọn thư mục...")
        pick_out.clicked.connect(self._pick_output_dir)
        source_layout.addWidget(QLabel("Xuất ra"), 1, 0)
        source_layout.addWidget(self.output_input, 1, 1)
        source_layout.addWidget(pick_out, 1, 2)

        self.recent_combo = QComboBox()
        self.recent_combo.addItem("— Nguồn đã dùng gần đây —")
        for item in self.settings.recent_sources:
            self.recent_combo.addItem(item)
        self.recent_combo.activated.connect(self._use_recent)
        source_layout.addWidget(QLabel("Gần đây"), 2, 0)
        source_layout.addWidget(self.recent_combo, 2, 1, 1, 2)
        source_layout.setColumnStretch(1, 1)
        layout.addWidget(source_box)

        # --- Ngôn ngữ ---
        lang_box = QGroupBox("Ngôn ngữ")
        lang_layout = QGridLayout(lang_box)
        self.source_lang = QComboBox()
        for code, label in LANGUAGES.items():
            self.source_lang.addItem(label, code)
        self.target_lang = QComboBox()
        for code, label in TARGET_LANGUAGES.items():
            self.target_lang.addItem(label, code)
        lang_layout.addWidget(QLabel("Ngôn ngữ gốc"), 0, 0)
        lang_layout.addWidget(self.source_lang, 0, 1)
        lang_layout.addWidget(QLabel("Dịch sang"), 0, 2)
        lang_layout.addWidget(self.target_lang, 0, 3)
        lang_layout.setColumnStretch(1, 1)
        lang_layout.setColumnStretch(3, 1)
        layout.addWidget(lang_box)

        # --- Bước xử lý ---
        steps_box = QGroupBox("Các bước sẽ chạy")
        steps_layout = QGridLayout(steps_box)
        self.chk_separate = QCheckBox("Tách giọng nói khỏi nhạc nền (Demucs)")
        self.chk_translate = QCheckBox("Dịch phụ đề bằng AI qua Proxy Server")
        self.chk_dubbing = QCheckBox("Lồng tiếng AI khớp thời lượng (XTTS-v2)")
        self.chk_voice_clone = QCheckBox("Nhái giọng nhân vật gốc (voice cloning)")
        self.chk_burn = QCheckBox("Ghi phụ đề chết vào video (burn-in)")
        self.chk_ducking = QCheckBox("Auto-ducking: hạ nhạc nền khi có thoại")
        boxes = (self.chk_separate, self.chk_translate, self.chk_dubbing,
                 self.chk_voice_clone, self.chk_burn, self.chk_ducking)
        for index, box in enumerate(boxes):
            steps_layout.addWidget(box, index // 2, index % 2)
        steps_layout.setColumnStretch(0, 1)
        steps_layout.setColumnStretch(1, 1)

        self.chk_translate.toggled.connect(self._sync_dependencies)
        self.chk_dubbing.toggled.connect(self._sync_dependencies)

        self.plan_label = QLabel()
        self.plan_label.setObjectName("subtitle")
        self.plan_label.setWordWrap(True)
        steps_layout.addWidget(self.plan_label, 3, 0, 1, 2)
        layout.addWidget(steps_box)

        layout.addStretch(1)
        return page

    def _build_advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        asr_box = QGroupBox("Nhận dạng giọng nói (Faster-Whisper)")
        asr_form = QFormLayout(asr_box)
        self.model_combo = QComboBox()
        self.model_combo.addItems(WHISPER_MODELS)
        self.device_combo = QComboBox()
        self.device_combo.addItems(DEVICES)
        self.compute_combo = QComboBox()
        self.compute_combo.addItems(COMPUTE_TYPES)
        self.chk_vad = QCheckBox("Dùng Silero VAD lọc khoảng lặng (nhanh hơn ~4x)")
        asr_form.addRow("Model", self.model_combo)
        asr_form.addRow("Thiết bị", self.device_combo)
        asr_form.addRow("Kiểu tính toán", self.compute_combo)
        asr_form.addRow("", self.chk_vad)
        layout.addWidget(asr_box)

        proxy_box = QGroupBox("Proxy Server dịch thuật")
        proxy_form = QFormLayout(proxy_box)
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://127.0.0.1:8000")
        test_row = QHBoxLayout()
        test_btn = QPushButton("Kiểm tra kết nối")
        test_btn.clicked.connect(self._test_proxy)
        self.proxy_status = QLabel("Chưa kiểm tra")
        self.proxy_status.setObjectName("subtitle")
        test_row.addWidget(test_btn)
        test_row.addWidget(self.proxy_status, stretch=1)
        proxy_form.addRow("Địa chỉ", self.proxy_input)
        proxy_form.addRow("", test_row)
        layout.addWidget(proxy_box)

        dub_box = QGroupBox("Lồng tiếng")
        dub_form = QFormLayout(dub_box)
        speaker_row = QHBoxLayout()
        self.speaker_input = QLineEdit()
        self.speaker_input.setPlaceholderText("Để trống = tự trích giọng mẫu từ vocal gốc")
        pick_speaker = QPushButton("Chọn...")
        pick_speaker.clicked.connect(self._pick_speaker_file)
        speaker_row.addWidget(self.speaker_input)
        speaker_row.addWidget(pick_speaker)

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(1.0, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)

        self.ducking_spin = QDoubleSpinBox()
        self.ducking_spin.setRange(-30.0, 0.0)
        self.ducking_spin.setSingleStep(1.0)
        self.ducking_spin.setSuffix(" dB")

        self.chk_keep = QCheckBox("Giữ lại file trung gian trong workspace (để debug)")

        dub_form.addRow("Giọng mẫu", speaker_row)
        dub_form.addRow("Tăng tốc tối đa", self.speed_spin)
        dub_form.addRow("Mức hạ nhạc nền", self.ducking_spin)
        dub_form.addRow("", self.chk_keep)
        layout.addWidget(dub_box)

        layout.addStretch(1)
        return page

    def _build_environment_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel(
            "Các engine AI được nạp khi cần. Thiếu engine nào thì bước tương ứng "
            "sẽ bị tắt hoặc chạy ở chế độ suy giảm."
        )
        info.setObjectName("subtitle")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.env_container = QWidget()
        self.env_layout = QVBoxLayout(self.env_container)
        self.env_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.env_container)
        scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(scroll, stretch=1)

        refresh = QPushButton("Kiểm tra lại")
        refresh.clicked.connect(self._refresh_environment)
        layout.addWidget(refresh, alignment=Qt.AlignLeft)
        return page

    def _build_license_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        box = QGroupBox("License")
        form = QFormLayout(box)
        self.hwid_field = QLineEdit(get_hwid())
        self.hwid_field.setReadOnly(True)
        copy_btn = QPushButton("Sao chép HWID")
        copy_btn.clicked.connect(self._copy_hwid)

        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("Dán license key được cấp")
        self.license_input.editingFinished.connect(self._refresh_license)
        self.license_status = QLabel()
        self.license_status.setWordWrap(True)

        form.addRow("Mã máy (HWID)", self.hwid_field)
        form.addRow("", copy_btn)
        form.addRow("License key", self.license_input)
        form.addRow("Trạng thái", self.license_status)
        layout.addWidget(box)

        note = QLabel(
            "Gửi HWID cho nhà phát hành để nhận license. License được ký RSA và "
            "khoá theo từng máy."
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_progress_panel(self) -> QWidget:
        panel = QGroupBox("Tiến độ")
        layout = QVBoxLayout(panel)

        self.stage_label = QLabel("Sẵn sàng.")
        self.stage_label.setObjectName("stage")
        layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(100)
        self.log_view.setMaximumHeight(150)
        layout.addWidget(self.log_view)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("▶  Bắt đầu xử lý")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Dừng")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.open_btn = QPushButton("Mở thư mục kết quả")
        self.open_btn.clicked.connect(self._open_output)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.open_btn)
        layout.addLayout(buttons)
        return panel

    # ------------------------------------------------------------ cấu hình <-> UI
    def _apply_config(self, config: JobConfig) -> None:
        self.source_input.setText(config.source)
        self.output_input.setText(config.output_dir)
        self._select_data(self.source_lang, config.source_lang)
        self._select_data(self.target_lang, config.target_lang)
        self.chk_separate.setChecked(config.separate_audio)
        self.chk_translate.setChecked(config.translate)
        self.chk_dubbing.setChecked(config.dubbing)
        self.chk_voice_clone.setChecked(config.voice_clone)
        self.chk_burn.setChecked(config.burn_subtitles)
        self.chk_ducking.setChecked(config.auto_ducking)
        self.model_combo.setCurrentText(config.whisper_model)
        self.device_combo.setCurrentText(config.device)
        self.compute_combo.setCurrentText(config.compute_type)
        self.chk_vad.setChecked(config.vad_filter)
        self.proxy_input.setText(config.proxy_url)
        self.license_input.setText(config.license_key)
        self.speaker_input.setText(config.tts_speaker_wav)
        self.speed_spin.setValue(config.max_speed_ratio)
        self.ducking_spin.setValue(config.ducking_db)
        self.chk_keep.setChecked(config.keep_intermediates)
        self._sync_dependencies()

    def collect_config(self) -> JobConfig:
        return JobConfig(
            source=self.source_input.text().strip(),
            output_dir=self.output_input.text().strip(),
            source_lang=self.source_lang.currentData(),
            target_lang=self.target_lang.currentData(),
            whisper_model=self.model_combo.currentText(),
            device=self.device_combo.currentText(),
            compute_type=self.compute_combo.currentText(),
            vad_filter=self.chk_vad.isChecked(),
            separate_audio=self.chk_separate.isChecked(),
            translate=self.chk_translate.isChecked(),
            proxy_url=self.proxy_input.text().strip(),
            license_key=self.license_input.text().strip(),
            dubbing=self.chk_dubbing.isChecked(),
            voice_clone=self.chk_voice_clone.isChecked(),
            tts_speaker_wav=self.speaker_input.text().strip(),
            max_speed_ratio=self.speed_spin.value(),
            burn_subtitles=self.chk_burn.isChecked(),
            auto_ducking=self.chk_ducking.isChecked(),
            ducking_db=self.ducking_spin.value(),
            keep_intermediates=self.chk_keep.isChecked(),
        )

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_dependencies(self) -> None:
        """Lồng tiếng cần bản dịch; voice cloning cần lồng tiếng."""
        if not self.chk_translate.isChecked():
            self.chk_dubbing.setChecked(False)
        self.chk_dubbing.setEnabled(self.chk_translate.isChecked())
        self.chk_voice_clone.setEnabled(self.chk_dubbing.isChecked())
        self.chk_ducking.setEnabled(self.chk_dubbing.isChecked())

        stages = plan_stages(self.collect_config())
        self.plan_label.setText(
            "Sẽ chạy " + str(len(stages)) + " bước:  "
            + "  →  ".join(s.label for s in stages)
        )

    # ----------------------------------------------------------------- hành động
    def _pick_source_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn video", "", VIDEO_FILTER)
        if path:
            self.source_input.setText(path)

    def _pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất", self.output_input.text())
        if path:
            self.output_input.setText(path)

    def _pick_speaker_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file giọng mẫu", "", "Audio (*.wav *.mp3 *.flac);;Tất cả file (*)"
        )
        if path:
            self.speaker_input.setText(path)

    def _use_recent(self, index: int) -> None:
        if index > 0:
            self.source_input.setText(self.recent_combo.itemText(index))

    def _copy_hwid(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.hwid_field.text())
        self.statusBar().showMessage("Đã sao chép HWID.", 3000)

    def _test_proxy(self) -> None:
        url = self.proxy_input.text().strip()
        if not url:
            self.proxy_status.setText("Chưa nhập địa chỉ.")
            return
        self.proxy_status.setText("Đang kiểm tra...")
        ok = TranslatorClient(url, self.license_input.text().strip()).health()
        color = OK if ok else DANGER
        message = "Kết nối tốt" if ok else "Không kết nối được"
        self.proxy_status.setText(f'<span style="color:{color}">{message}</span>')

    def _refresh_license(self) -> None:
        info = verify_license(self.license_input.text().strip())
        color = OK if info.valid else DANGER
        self.license_status.setText(f'<span style="color:{color}">{info.status_text}</span>')

    def _refresh_environment(self) -> None:
        while self.env_layout.count():
            item = self.env_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        checks = run_checks()
        for check in checks:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            color = OK if check.ok else (DANGER if check.required else WARN)
            label = QLabel(f'<span style="color:{color}">{check.icon}</span>  <b>{check.name}</b>')
            detail = QLabel(check.detail + (f"  ·  {check.fix}" if check.fix else ""))
            detail.setObjectName("subtitle")
            detail.setWordWrap(True)
            row_layout.addWidget(label)
            row_layout.addWidget(detail, stretch=1)
            self.env_layout.addWidget(row)
        self.env_layout.addStretch(1)

        problems = blocking_problems(checks)
        if problems:
            names = ", ".join(p.name for p in problems)
            self.header_status.setText(
                f'<span style="color:{WARN}">Thiếu: {names}</span>'
            )
        else:
            self.header_status.setText(f'<span style="color:{OK}">Môi trường sẵn sàng</span>')

    def _open_output(self) -> None:
        path = Path(self.output_input.text().strip() or ".")
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # -------------------------------------------------------------- chạy job
    def _start(self) -> None:
        config = self.collect_config()
        try:
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Cấu hình chưa hợp lệ", str(exc))
            return

        problems = blocking_problems(run_checks())
        if problems:
            names = "\n".join(f"• {p.name}: {p.fix or p.detail}" for p in problems)
            answer = QMessageBox.question(
                self, "Thiếu thành phần bắt buộc",
                f"Những thành phần sau chưa sẵn sàng:\n\n{names}\n\nVẫn chạy thử?",
            )
            if answer != QMessageBox.Yes:
                self.tabs.setCurrentIndex(2)
                return

        self.settings.last_job = config
        self.settings.remember_source(config.source)
        self.settings.save()

        self.log_view.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.last_result = None

        self.worker = PipelineWorker(config, self)
        self.worker.log.connect(self._append_log)
        self.worker.stage_changed.connect(self._on_stage)
        self.worker.progress_changed.connect(lambda v: self.progress_bar.setValue(int(v * 1000)))
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker:
            self.cancel_btn.setEnabled(False)
            self.worker.cancel()

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _on_stage(self, name: str, index: int, total: int) -> None:
        self.stage_label.setText(f"Bước {index}/{total}: {name}")

    def _on_success(self, result: PipelineResult) -> None:
        self.last_result = result
        self.progress_bar.setValue(1000)
        self.stage_label.setText("Hoàn tất.")
        files = "\n".join(f"• {p.name}" for p in result.outputs())
        QMessageBox.information(
            self, "Xong",
            f"Đã xử lý xong.\n\nFile kết quả:\n{files}\n\nThư mục: {self.output_input.text()}",
        )

    def _on_failure(self, message: str) -> None:
        self.stage_label.setText(f'<span style="color:{DANGER}">Thất bại</span>')
        self._append_log(f"❌ {message}")
        QMessageBox.critical(self, "Lỗi", message)

    def _on_cancelled(self) -> None:
        self.stage_label.setText("Đã dừng.")
        self.progress_bar.setValue(0)

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.worker = None

    # -------------------------------------------------------------- vòng đời
    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self, "Đang xử lý", "Job đang chạy. Dừng và thoát?"
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)

        self.settings.last_job = self.collect_config()
        self.settings.save()
        event.accept()


def main() -> int:
    """Cho phép mở app bằng `python -m desktop.main_window`."""
    from desktop.app import main as launch

    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
