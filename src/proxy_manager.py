"""Chạy Proxy Server dịch thuật ngầm ngay trong tiến trình app.

Người dùng không phải mở thêm cửa sổ CMD nào: app tự bật uvicorn bằng
subprocess.Popen lúc khởi động và tự tắt khi đóng app.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
from urllib import error, request

from .app_config import AppConfig
from .utils import module_available

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 25.0     # giây chờ server sẵn sàng
SHUTDOWN_TIMEOUT = 5.0     # giây chờ tắt êm trước khi kill
MAX_LOG_LINES = 200


@dataclass
class StartResult:
    ok: bool
    message: str
    reused: bool = False        # True = đã có server chạy sẵn, không cần bật mới


def _no_window_flags() -> dict:
    """Trên Windows: chạy uvicorn không bung cửa sổ console."""
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def probe_health(url: str, timeout: float = 2.0) -> Optional[dict]:
    """Trả về payload /health nếu có server sống ở đó, None nếu không."""
    try:
        with request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except (error.URLError, OSError, ValueError):
        pass
    return None


class ProxyServerManager:
    """Bật/tắt uvicorn dưới dạng tiến trình con.

    Dùng ``instance()`` để mọi entry point (run_desktop.py, python -m desktop)
    chia sẻ cùng một server thay vì bật trùng nhau.
    """

    _instance: Optional["ProxyServerManager"] = None

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        self.config = config or AppConfig.load()
        self.process: Optional[subprocess.Popen] = None
        self.logs: List[str] = []
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "ProxyServerManager":
        if cls._instance is None:
            cls._instance = cls()
            atexit.register(cls._instance.stop)
        return cls._instance

    # ------------------------------------------------------------------ trạng thái
    @property
    def url(self) -> str:
        return self.config.proxy_url

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def is_healthy(self) -> bool:
        return probe_health(self.url) is not None

    def recent_logs(self, count: int = 15) -> str:
        return "\n".join(self.logs[-count:])

    # ------------------------------------------------------------------ vòng đời
    def start(self, api_key: Optional[str] = None) -> StartResult:
        """Bật server. Idempotent: đã chạy rồi thì không bật lại."""
        with self._lock:
            if self.is_running():
                return StartResult(True, "Server nhúng đang chạy sẵn.", reused=True)

            if probe_health(self.url) is not None:
                return StartResult(
                    True,
                    f"Đã có server chạy sẵn ở {self.url} - dùng luôn, không bật thêm.",
                    reused=True,
                )

            missing = [name for name in ("fastapi", "uvicorn") if not module_available(name)]
            if missing:
                return StartResult(
                    False,
                    f"Thiếu {' và '.join(missing)} nên không bật được server dịch thuật. "
                    f"Cài bằng: pip install {' '.join(missing)}",
                )

            provider = self.config.provider
            key = api_key if api_key is not None else self.config.effective_api_key()
            env = os.environ.copy()
            env["SUBAI_PROVIDER"] = provider
            env["SUBAI_API_KEY"] = key
            env["SUBAI_MODEL"] = self.config.model_for(provider)
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            command = [
                sys.executable, "-m", "uvicorn", "server.proxy_server:app",
                "--host", "127.0.0.1",
                "--port", str(self.config.proxy_port),
                "--log-level", "warning",
            ]

            self.logs.clear()
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **_no_window_flags(),
                )
            except OSError as exc:
                return StartResult(False, f"Không khởi chạy được uvicorn: {exc}")

            self._reader = threading.Thread(target=self._drain_output, daemon=True)
            self._reader.start()

        return self._await_ready()

    def _await_ready(self) -> StartResult:
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            if not self.is_running():
                tail = self.recent_logs(10)
                return StartResult(
                    False,
                    "Server dịch thuật tắt ngay khi vừa bật."
                    + (f"\n\nLog:\n{tail}" if tail else ""),
                )
            if probe_health(self.url) is not None:
                return StartResult(True, f"Server dịch thuật đã sẵn sàng ở {self.url}")
            time.sleep(0.4)

        self.stop()
        return StartResult(
            False,
            f"Server không phản hồi sau {STARTUP_TIMEOUT:.0f} giây."
            + (f"\n\nLog:\n{self.recent_logs(10)}" if self.logs else ""),
        )

    def _drain_output(self) -> None:
        """Đọc log uvicorn để hiển thị khi có lỗi (nếu không đọc, pipe sẽ đầy và treo)."""
        process = self.process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            self.logs.append(line.rstrip())
            del self.logs[:-MAX_LOG_LINES]

    def stop(self) -> None:
        """Tắt êm; quá hạn thì kill. An toàn khi gọi nhiều lần."""
        with self._lock:
            process, self.process = self.process, None

        if process is None or process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                pass

    def restart(self, api_key: Optional[str] = None) -> StartResult:
        """Dùng sau khi người dùng đổi API key ở giao diện."""
        self.stop()
        time.sleep(0.3)     # nhường cổng cho tiến trình mới
        return self.start(api_key)


def start_background_proxy(log: Optional[Callable[[str], None]] = None) -> StartResult:
    """Tiện ích cho entry point: bật server nếu cấu hình cho phép."""
    manager = ProxyServerManager.instance()
    if not manager.config.auto_start_proxy:
        return StartResult(True, "auto_start=false trong config.ini - bỏ qua server nhúng.")

    result = manager.start()
    if log:
        log(result.message)
    return result
