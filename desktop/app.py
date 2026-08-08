"""Điểm khởi động SubAI Studio."""

from __future__ import annotations

import sys
from pathlib import Path

# Cho phép chạy trực tiếp `python desktop/app.py` mà vẫn import được package src.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop.main_window import MainWindow  # noqa: E402
from desktop.theme import STYLESHEET  # noqa: E402
from src.config import APP_NAME  # noqa: E402


def create_app(argv: list[str] | None = None) -> QApplication:
    """Tạo QApplication đã gắn theme (tách riêng để test dùng lại được)."""
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SubAI Team")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 10))
    return app


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = create_app()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
