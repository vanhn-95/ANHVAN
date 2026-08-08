"""Kênh báo tiến độ giữa pipeline và giao diện."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .utils import CancelledError


class ProgressReporter:
    """Cầu nối pipeline -> UI.

    Pipeline chỉ gọi log()/stage()/progress()/check_cancelled(); phía UI cắm
    callback vào để hiển thị. Mặc định là in ra stdout (dùng cho CLI/test).
    """

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_stage: Optional[Callable[[str, int, int], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._on_log = on_log or (lambda msg: print(msg))
        self._on_stage = on_stage or (lambda name, index, total: None)
        self._on_progress = on_progress or (lambda value: None)
        self._cancel = threading.Event()
        self._stage_index = 0
        self._stage_total = 0
        self._stage_base = 0.0
        self._stage_weight = 1.0

    # --- Điều khiển ---
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise CancelledError("Đã dừng theo yêu cầu người dùng.")

    # --- Báo cáo ---
    def log(self, message: str) -> None:
        self._on_log(message)

    def begin_stage(self, name: str, index: int, total: int, base: float, weight: float) -> None:
        self._stage_index, self._stage_total = index, total
        self._stage_base, self._stage_weight = base, weight
        self._on_stage(name, index, total)
        self._on_progress(base)

    def progress(self, fraction: float) -> None:
        """fraction: 0..1 trong phạm vi stage hiện tại."""
        fraction = min(1.0, max(0.0, fraction))
        self._on_progress(self._stage_base + fraction * self._stage_weight)

    def end_stage(self) -> None:
        self._on_progress(self._stage_base + self._stage_weight)
