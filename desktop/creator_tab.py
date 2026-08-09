"""Tab “Tự động hoá nâng cao (Affiliate Bot)”.

Tab tự quản job của nó (worker riêng, nút Bắt đầu/Dừng riêng) nhưng dùng chung
thanh tiến độ + khung log ở đáy cửa sổ thông qua ``host``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.app_config import AppConfig
from src.config import TARGET_LANGUAGES, WHISPER_MODELS
from src.creator_pipeline import CreatorConfig, CreatorResult, plan_stages
from src.intro_maker import BACKGROUNDS
from src.music_mixer import MUSIC_LIBRARY, ensure_library, list_library
from src.providers import PROVIDERS
from src.script_writer import ScriptWriter

from desktop.theme import DANGER, MUTED, OK, WARN
from desktop.worker import CreatorWorker

AUDIO_FILTER = "Nhạc (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;Tất cả file (*)"

BACKGROUND_LABELS = {
    "tim": "Tím gradient",
    "cam": "Cam - hồng",
    "xanh": "Xanh đêm",
    "toi": "Xám tối",
}


class CreatorTab(QWidget):
    """Giao diện Bot: nguồn video, intro, nhạc, kịch bản, nút chạy."""

    def __init__(self, host, app_config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.app_config = app_config
        self.worker: Optional[CreatorWorker] = None
        self.last_result: Optional[CreatorResult] = None

        # Phần cài đặt cuộn được, nhưng hàng nút luôn nằm cố định phía dưới để
        # "Bắt đầu chạy Bot" không bị trôi khỏi màn hình.
        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(12)
        settings_layout.addWidget(self._build_source_box())
        settings_layout.addWidget(self._build_script_box())
        settings_layout.addWidget(self._build_intro_box())
        settings_layout.addWidget(self._build_music_box())
        settings_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(settings)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self._build_action_row())

        self._sync_enabled()

    # --------------------------------------------------------------- xây dựng UI
    def _build_source_box(self) -> QWidget:
        box = QGroupBox("Nguồn video")
        grid = QGridLayout(box)

        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText(
            "Dán link Douyin / RedNote (xiaohongshu) / YouTube / TikTok... hoặc chọn file"
        )
        browse = QPushButton("Chọn file...")
        browse.clicked.connect(self._pick_source)
        grid.addWidget(QLabel("Link video"), 0, 0)
        grid.addWidget(self.source_input, 0, 1)
        grid.addWidget(browse, 0, 2)

        self.output_input = QLineEdit(str(Path.home() / "SubAI" / "creator"))
        pick_out = QPushButton("Chọn thư mục...")
        pick_out.clicked.connect(self._pick_output)
        grid.addWidget(QLabel("Xuất ra"), 1, 0)
        grid.addWidget(self.output_input, 1, 1)
        grid.addWidget(pick_out, 1, 2)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.target_lang = QComboBox()
        for code, label in TARGET_LANGUAGES.items():
            self.target_lang.addItem(label, code)
        self.target_lang.setCurrentIndex(max(0, self.target_lang.findData("vi")))
        self.model_combo = QComboBox()
        self.model_combo.addItems(WHISPER_MODELS)
        self.model_combo.setCurrentText("medium")
        row_layout.addWidget(QLabel("Ngôn ngữ đích"))
        row_layout.addWidget(self.target_lang, 1)
        row_layout.addWidget(QLabel("Model nghe"))
        row_layout.addWidget(self.model_combo, 1)
        grid.addWidget(row, 2, 0, 1, 3)
        grid.setColumnStretch(1, 1)

        notice = QLabel(
            "⚠ Bạn chịu trách nhiệm về quyền sử dụng video nguồn. Đăng lại video của "
            "người khác khi chưa được phép có thể bị gỡ hoặc khoá kênh."
        )
        notice.setObjectName("subtitle")
        notice.setWordWrap(True)
        grid.addWidget(notice, 3, 0, 1, 3)
        return box

    def _build_script_box(self) -> QWidget:
        box = QGroupBox("Kịch bản AI && giọng đọc")   # "&&" vì Qt nuốt "&" đơn
        form = QFormLayout(box)

        self.provider_combo = QComboBox()
        for name, spec in PROVIDERS.items():
            self.provider_combo.addItem(spec.label, name)
        self.provider_combo.setCurrentIndex(
            max(0, self.provider_combo.findData(self.app_config.provider))
        )
        form.addRow("Nhà cung cấp AI", self.provider_combo)

        self.chk_rewrite = QCheckBox("Tự động viết lại kịch bản AI (phong cách TikTok)")
        self.chk_rewrite.setChecked(True)
        self.chk_tts = QCheckBox("Lồng tiếng TTS thay thế giọng gốc")
        self.chk_tts.setChecked(True)
        self.chk_keep_sub = QCheckBox("Giữ lại phụ đề (xuất file .srt)")
        self.chk_keep_sub.setChecked(True)
        self.chk_clone = QCheckBox("Nhái giọng nhân vật gốc (voice cloning)")
        for widget in (self.chk_rewrite, self.chk_tts, self.chk_keep_sub, self.chk_clone):
            widget.toggled.connect(self._sync_enabled)
            form.addRow("", widget)

        hint = QLabel(
            "Kịch bản viết lại giữ nguyên số câu và mốc thời gian của video gốc, "
            "nên giọng đọc luôn khớp hình. Câu nào cũng có dấu câu đầy đủ để TTS "
            "đọc có nhịp."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        form.addRow("", hint)
        return box

    def _build_intro_box(self) -> QWidget:
        box = QGroupBox("Intro 3 giây")
        form = QFormLayout(box)

        self.chk_intro = QCheckBox("Tạo intro 3 giây ghép vào đầu video")
        self.chk_intro.setChecked(True)
        self.chk_intro.toggled.connect(self._sync_enabled)
        form.addRow("", self.chk_intro)

        self.intro_input = QLineEdit()
        self.intro_input.setPlaceholderText(
            "VD: MẸO HAY MỖI NGÀY · REVIEW MỸ PHẨM CỰC CHẤT · tên kênh của bạn"
        )
        form.addRow("Nội dung intro", self.intro_input)

        self.chk_intro_ai = QCheckBox("Tự động tạo Intro AI nếu để trống")
        self.chk_intro_ai.setChecked(True)
        form.addRow("", self.chk_intro_ai)

        self.intro_bg = QComboBox()
        for key in BACKGROUNDS:
            self.intro_bg.addItem(BACKGROUND_LABELS.get(key, key), key)
        form.addRow("Nền intro", self.intro_bg)
        return box

    def _build_music_box(self) -> QWidget:
        box = QGroupBox("Nhạc nền")
        form = QFormLayout(box)

        self.chk_music = QCheckBox("Ghép nhạc nền mới")
        self.chk_music.setChecked(True)
        self.chk_music.toggled.connect(self._sync_enabled)
        form.addRow("", self.chk_music)

        music_row = QHBoxLayout()
        self.music_input = QLineEdit()
        self.music_input.setPlaceholderText(
            "Để trống = AI chọn từ thư viện royalty-free theo cảm xúc video"
        )
        pick_music_btn = QPushButton("Chọn nhạc...")
        pick_music_btn.clicked.connect(self._pick_music)
        music_row.addWidget(self.music_input)
        music_row.addWidget(pick_music_btn)
        form.addRow("File nhạc", music_row)

        library_row = QHBoxLayout()
        self.library_label = QLabel()
        self.library_label.setObjectName("subtitle")
        open_library = QPushButton("Mở thư viện")
        open_library.clicked.connect(self._open_library)
        suggest = QPushButton("AI gợi ý chủ đề nhạc")
        suggest.clicked.connect(self._suggest_genres)
        library_row.addWidget(self.library_label, 1)
        library_row.addWidget(suggest)
        library_row.addWidget(open_library)
        form.addRow("Thư viện", library_row)

        self.music_db = QDoubleSpinBox()
        self.music_db.setRange(-40.0, 0.0)
        self.music_db.setValue(-15.0)
        self.music_db.setSingleStep(1.0)
        self.music_db.setSuffix(" dB")
        form.addRow("Âm lượng nhạc", self.music_db)

        self.chk_ducking = QCheckBox("Auto-ducking: hạ nhạc khi có lời thoại")
        self.chk_ducking.setChecked(True)
        form.addRow("", self.chk_ducking)

        self.chk_separate = QCheckBox("Tách giọng khỏi nhạc gốc bằng Demucs")
        self.chk_separate.setChecked(True)
        form.addRow("", self.chk_separate)

        note = QLabel(
            "App không tải nhạc từ TikTok/Douyin: nhạc trên các nền tảng đó chỉ được "
            "cấp phép dùng trong trình soạn thảo của chính họ, tải về ghép vào video "
            "là vi phạm bản quyền và dễ bị gỡ tiếng. Hãy dùng nhạc bạn có quyền."
        )
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        form.addRow("", note)

        self._refresh_library_label()
        return box

    def _build_action_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self.start_btn = QPushButton("🤖  Bắt đầu chạy Bot")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Dừng")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        open_btn = QPushButton("Mở thư mục kết quả")
        open_btn.clicked.connect(self._open_output)

        self.plan_label = QLabel()
        self.plan_label.setObjectName("subtitle")
        self.plan_label.setWordWrap(True)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.cancel_btn)
        layout.addWidget(self.plan_label, 1)
        layout.addWidget(open_btn)
        return row

    # ------------------------------------------------------------------ cấu hình
    def collect_config(self) -> CreatorConfig:
        provider = self.provider_combo.currentData() or self.app_config.provider
        return CreatorConfig(
            source=self.source_input.text().strip(),
            output_dir=self.output_input.text().strip(),
            target_lang=self.target_lang.currentData() or "vi",
            whisper_model=self.model_combo.currentText(),
            provider=provider,
            api_key=self.app_config.effective_api_key(provider),
            model=self.app_config.model_for(provider),
            separate_audio=self.chk_separate.isChecked(),
            rewrite_script=self.chk_rewrite.isChecked(),
            tts_dubbing=self.chk_tts.isChecked(),
            voice_clone=self.chk_clone.isChecked(),
            keep_subtitles=self.chk_keep_sub.isChecked(),
            make_intro=self.chk_intro.isChecked(),
            add_music=self.chk_music.isChecked(),
            auto_ducking=self.chk_ducking.isChecked(),
            intro_text=self.intro_input.text().strip(),
            intro_auto_ai=self.chk_intro_ai.isChecked(),
            intro_background=self.intro_bg.currentData() or "tim",
            music_file=self.music_input.text().strip(),
            music_db=self.music_db.value(),
        )

    def _sync_enabled(self) -> None:
        self.chk_clone.setEnabled(self.chk_tts.isChecked())
        if not self.chk_tts.isChecked():
            self.chk_clone.setChecked(False)

        for widget in (self.intro_input, self.chk_intro_ai, self.intro_bg):
            widget.setEnabled(self.chk_intro.isChecked())
        for widget in (self.music_input, self.music_db, self.chk_ducking):
            widget.setEnabled(self.chk_music.isChecked())

        stages = plan_stages(self.collect_config())
        self.plan_label.setText(
            f"{len(stages)} bước: " + " → ".join(s.label for s in stages)
        )

    def _refresh_library_label(self) -> None:
        tracks = list_library()
        if tracks:
            self.library_label.setText(
                f'<span style="color:{OK}">{len(tracks)} bài trong '
                f"assets/royalty_free_music/</span>"
            )
        else:
            self.library_label.setText(
                f'<span style="color:{WARN}">Thư viện trống - bấm “Mở thư viện” '
                "rồi bỏ nhạc của bạn vào</span>"
            )

    # ------------------------------------------------------------------ hành động
    def _pick_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", "", "Video (*.mp4 *.mkv *.mov *.webm);;Tất cả file (*)"
        )
        if path:
            self.source_input.setText(path)

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục xuất", self.output_input.text()
        )
        if path:
            self.output_input.setText(path)

    def _pick_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn nhạc nền", "", AUDIO_FILTER)
        if path:
            self.music_input.setText(path)

    def _open_library(self) -> None:
        folder = ensure_library()
        self._reveal(folder)
        self._refresh_library_label()

    def _open_output(self) -> None:
        folder = Path(self.output_input.text().strip() or ".")
        folder.mkdir(parents=True, exist_ok=True)
        self._reveal(folder)

    @staticmethod
    def _reveal(folder: Path) -> None:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _suggest_genres(self) -> None:
        """Gợi ý thể loại nhạc. Chưa có script thì gợi ý theo bảng mặc định."""
        from src.script_writer import FALLBACK_GENRES

        lines = [f"• {mood}: {', '.join(genres)}" for mood, genres in FALLBACK_GENRES.items()]
        QMessageBox.information(
            self, "Gợi ý chủ đề nhạc",
            "Đặt tên file nhạc có chứa các từ khoá này để Bot tự khớp theo cảm xúc "
            "video:\n\n" + "\n".join(lines) +
            f"\n\nThư mục: {MUSIC_LIBRARY}\n\n"
            "Khi chạy Bot, AI sẽ đọc kịch bản để chọn cảm xúc rồi tìm file khớp.",
        )

    # ---------------------------------------------------------------- chạy job
    def start(self) -> None:
        config = self.collect_config()
        try:
            config.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Cấu hình chưa hợp lệ", str(exc))
            return

        if not self.host.claim_job(self):
            return

        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.host.set_progress(0.0)
        self.last_result = None

        self.worker = CreatorWorker(config, self)
        self.worker.log.connect(self.host.log)
        self.worker.stage_changed.connect(self.host.set_stage)
        self.worker.progress_changed.connect(self.host.set_progress)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def cancel(self) -> None:
        if self.worker:
            self.cancel_btn.setEnabled(False)
            self.worker.cancel()

    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _on_success(self, result: CreatorResult) -> None:
        self.last_result = result
        self.host.set_progress(1.0)
        self.host.set_stage("Bot chạy xong.", 0, 0)

        details = [f"• {path.name}" for path in result.outputs()]
        if result.intro_text:
            details.append(f"Intro: “{result.intro_text}”")
        if result.mood:
            details.append(f"Cảm xúc: {result.mood.mood}")
        if result.music and result.music.found:
            details.append(f"Nhạc: {result.music.path.name}")

        # Tự mở thư mục để lấy video đăng ngay.
        self._open_output()
        QMessageBox.information(
            self, "Bot chạy xong",
            "Video đã sẵn sàng để đăng.\n\n" + "\n".join(details) +
            f"\n\nThư mục: {self.output_input.text()}",
        )

    def _on_failure(self, message: str) -> None:
        self.host.log(f"❌ {message}")
        self.host.set_stage("Bot thất bại.", 0, 0)
        QMessageBox.critical(self, "Bot lỗi", message)

    def _on_cancelled(self) -> None:
        self.host.set_stage("Đã dừng Bot.", 0, 0)
        self.host.set_progress(0.0)

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.worker = None
        self.host.release_job(self)
