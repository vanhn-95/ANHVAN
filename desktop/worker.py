"""Chạy pipeline ở thread riêng để giao diện không bị đơ."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from typing import Optional

from src.config import JobConfig
from src.main_pipeline import Pipeline, PipelineResult
from src.progress import ProgressReporter
from src.proxy_manager import ProxyServerManager
from src.translator import ProxyStatus, TranslatorClient
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


class ProxyCheckWorker(QThread):
    """Khởi động lại server nhúng và/hoặc kiểm tra kết nối, ở thread nền.

    Bước verify gọi thẳng Gemini nên có thể mất vài giây - chạy trên UI thread
    sẽ làm cửa sổ đơ.
    """

    checked = Signal(object)     # ProxyStatus
    note = Signal(str)           # thông báo tiến trình cho người dùng

    def __init__(
        self,
        proxy_url: str,
        license_key: str = "",
        restart_with_key: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.proxy_url = proxy_url
        self.license_key = license_key
        self.restart_with_key = restart_with_key

    def run(self) -> None:
        if self.restart_with_key is not None:
            self.note.emit("Đang khởi động lại server dịch thuật...")
            result = ProxyServerManager.instance().restart(self.restart_with_key)
            if not result.ok:
                self.checked.emit(
                    ProxyStatus(False, "unreachable", "Không bật được server nhúng.", result.message)
                )
                return

        self.note.emit("Đang kiểm tra API key với Gemini...")
        try:
            status = TranslatorClient(self.proxy_url, self.license_key).diagnose()
        except Exception as exc:
            status = ProxyStatus(False, "error", "Lỗi khi kiểm tra.", f"{exc.__class__.__name__}: {exc}")
        self.checked.emit(status)


class CreatorWorker(QThread):
    """Chạy pipeline Auto Creator ở thread nền."""

    log = Signal(str)
    stage_changed = Signal(str, int, int)
    progress_changed = Signal(float)
    succeeded = Signal(object)   # CreatorResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.reporter = ProgressReporter(
            on_log=self.log.emit,
            on_stage=lambda name, index, total: self.stage_changed.emit(name, index, total),
            on_progress=self.progress_changed.emit,
        )

    def cancel(self) -> None:
        self.reporter.cancel()
        self.log.emit("Đang dừng Bot... chờ bước hiện tại kết thúc.")

    def run(self) -> None:
        from src.creator_pipeline import CreatorPipeline

        try:
            result = CreatorPipeline(self.config, self.reporter).run()
        except CancelledError:
            self.cancelled.emit()
        except PipelineError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Lỗi không mong đợi: {exc.__class__.__name__}: {exc}")
        else:
            self.succeeded.emit(result)
