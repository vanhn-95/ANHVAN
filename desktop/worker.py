"""Chạy pipeline ở thread riêng để giao diện không bị đơ."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.config import JobConfig
from src.main_pipeline import Pipeline, PipelineResult
from src.progress import ProgressReporter
from src.utils import CancelledError, PipelineError


class PipelineWorker(QThread):
    """Bọc Pipeline trong QThread và phát tín hiệu về UI thread."""

    log = Signal(str)
    stage_changed = Signal(str, int, int)
    progress_changed = Signal(float)
    succeeded = Signal(object)   # PipelineResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config: JobConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.reporter = ProgressReporter(
            on_log=self.log.emit,
            on_stage=lambda name, index, total: self.stage_changed.emit(name, index, total),
            on_progress=self.progress_changed.emit,
        )

    def cancel(self) -> None:
        self.reporter.cancel()
        self.log.emit("Đang dừng... chờ bước hiện tại kết thúc.")

    def run(self) -> None:  # chạy trong thread nền
        try:
            result: PipelineResult = Pipeline(self.config, self.reporter).run()
        except CancelledError:
            self.cancelled.emit()
        except PipelineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # lỗi ngoài dự tính - vẫn phải hiện cho người dùng
            self.failed.emit(f"Lỗi không mong đợi: {exc.__class__.__name__}: {exc}")
        else:
            self.succeeded.emit(result)
