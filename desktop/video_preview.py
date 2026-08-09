"""Khung xem trước video: hiện frame đầu tiên + thông tin khung hình."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.intro_maker import VideoInfo, probe_video
from src.utils import ffmpeg_path, human_duration, probe_duration

PLACEHOLDER = "Chưa có video\n\nChọn file hoặc dán link rồi bấm “Xem trước”"


def extract_first_frame(video: Path, target: Path, at_second: float = 1.0) -> Optional[Path]:
    """Trích một frame làm ảnh xem trước. Trả None nếu không làm được."""
    exe = ffmpeg_path()
    if not exe or not Path(video).is_file():
        return None

    duration = probe_duration(Path(video))
    timestamp = min(at_second, duration / 2) if duration else 0.0

    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-ss", f"{timestamp:.2f}", "-i", str(video),
         "-frames:v", "1", "-vf", "scale=480:-2", str(target)],
        capture_output=True, text=True,
    )
    return Path(target) if proc.returncode == 0 and Path(target).exists() else None


class PreviewWorker(QThread):
    """Trích frame ở thread nền - ffmpeg có thể mất một hai giây."""

    ready = Signal(str, object, float)   # đường dẫn ảnh, VideoInfo, thời lượng
    failed = Signal(str)

    def __init__(self, video: Path, parent=None) -> None:
        super().__init__(parent)
        self.video = Path(video)

    def run(self) -> None:
        try:
            target = Path(tempfile.gettempdir()) / f"subai_preview_{abs(hash(str(self.video)))}.jpg"
            frame = extract_first_frame(self.video, target)
            if frame is None:
                self.failed.emit("Không đọc được video này.")
                return
            self.ready.emit(str(frame), probe_video(self.video), probe_duration(self.video))
        except Exception as exc:
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")


class VideoPreview(QWidget):
    """Ảnh xem trước + dòng thông tin (kích thước, thời lượng, tỉ lệ)."""

    loaded = Signal(object, float)      # VideoInfo, duration

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.worker: Optional[PreviewWorker] = None
        self.info: Optional[VideoInfo] = None
        self.duration: float = 0.0
        self._pixmap: Optional[QPixmap] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.image = QLabel(PLACEHOLDER)
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(260, 300)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image.setStyleSheet(
            "background:#0f1116; border:1px solid #2e3441; border-radius:10px; color:#8b93a7;"
        )
        layout.addWidget(self.image, stretch=1)

        self.caption = QLabel("—")
        self.caption.setObjectName("subtitle")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

    # ------------------------------------------------------------------- nạp ảnh
    def load(self, source: str) -> None:
        path = Path(source.strip()).expanduser()
        if not source.strip():
            self.clear("Chưa nhập nguồn video.")
            return
        if not path.is_file():
            # URL thì phải tải xong mới có frame; Bot sẽ tự tải khi chạy.
            self.clear(
                "Nguồn là đường link — ảnh xem trước sẽ có sau khi Bot tải video về.\n"
                "Muốn xem ngay thì chọn file trong máy."
            )
            return

        if self.worker and self.worker.isRunning():
            return

        self.image.setText("Đang đọc video...")
        self.worker = PreviewWorker(path, self)
        self.worker.ready.connect(self._on_ready)
        self.worker.failed.connect(lambda message: self.clear(f"Lỗi: {message}"))
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_ready(self, frame_path: str, info: VideoInfo, duration: float) -> None:
        pixmap = QPixmap(frame_path)
        if pixmap.isNull():
            self.clear("Không hiển thị được ảnh xem trước.")
            return

        self._pixmap = pixmap
        self.info = info
        self.duration = duration
        self._rescale()

        ratio = _aspect_label(info)
        self.caption.setText(
            f"{info.width}×{info.height} · {ratio} · {info.fps:.0f}fps · "
            f"{human_duration(duration)}"
        )
        self.loaded.emit(info, duration)

    def _on_finished(self) -> None:
        self.worker = None

    def clear(self, message: str = PLACEHOLDER) -> None:
        self._pixmap = None
        self.info = None
        self.duration = 0.0
        self.image.setPixmap(QPixmap())
        self.image.setText(message)
        self.caption.setText("—")

    # ------------------------------------------------------------------ hiển thị
    def _rescale(self) -> None:
        if self._pixmap is None:
            return
        self.image.setPixmap(self._pixmap.scaled(
            self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()


def _aspect_label(info: VideoInfo) -> str:
    """Nhãn tỉ lệ dễ đọc, kèm cảnh báo nếu không phải khung dọc."""
    if info.height <= 0:
        return "?"
    ratio = info.width / info.height
    if abs(ratio - 9 / 16) < 0.02:
        return "9:16 dọc sẵn ✓"
    if abs(ratio - 1.0) < 0.02:
        return "1:1 vuông → sẽ thêm nền"
    if ratio > 1:
        return "ngang → sẽ thêm nền mờ hai bên"
    return "dọc → sẽ scale về 9:16"
