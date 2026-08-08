"""Client gọi Proxy Server dịch thuật (Gemini nằm phía server)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import List, Sequence
from urllib import error, request

from .progress import ProgressReporter
from .utils import PipelineError, Segment

BATCH_SIZE = 40
MAX_RETRIES = 3


@dataclass
class ProxyStatus:
    """Kết quả nút 'Kiểm tra kết nối' - phân biệt rõ từng nguyên nhân."""

    ok: bool
    code: str        # ok | no_url | unreachable | no_key | bad_key | quota | bad_model | network | error
    message: str
    hint: str = ""

    @property
    def full_text(self) -> str:
        return f"{self.message} {self.hint}".strip()


class TranslatorClient:
    """Gửi lô câu thoại lên proxy và nhận bản dịch giữ nguyên thứ tự.

    API key Gemini không bao giờ nằm ở máy client - proxy giữ key và chỉ nhận
    license key để xác thực.
    """

    def __init__(self, proxy_url: str, license_key: str = "", timeout: int = 120) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.license_key = license_key
        self.timeout = timeout

    def health(self) -> bool:
        try:
            req = request.Request(f"{self.proxy_url}/health", method="GET")
            with request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            return False

    def diagnose(self, timeout: int = 30) -> ProxyStatus:
        """Kiểm tra từng lớp một và nói rõ hỏng ở đâu: proxy, key, hay Gemini."""
        if not self.proxy_url:
            return ProxyStatus(False, "no_url", "Chưa nhập địa chỉ Proxy Server.")

        # Lớp 1 - proxy có sống không?
        try:
            with request.urlopen(f"{self.proxy_url}/health", timeout=10) as resp:
                health = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            return ProxyStatus(
                False, "unreachable",
                f"Proxy trả về HTTP {exc.code} ở /health.",
                "Địa chỉ có đúng là SubAI Proxy Server không?",
            )
        except Exception as exc:
            return ProxyStatus(
                False, "unreachable",
                f"Không kết nối được tới {self.proxy_url}.",
                f"Server dịch thuật chưa chạy hoặc sai cổng. ({exc.__class__.__name__})",
            )

        # Lớp 2 - proxy có key chưa?
        label = health.get("provider_label", "nhà cung cấp AI")
        if not health.get("api_key_configured"):
            return ProxyStatus(
                False, "no_key",
                f"Proxy đang chạy nhưng chưa có API key cho {label}.",
                "Nhập API key vào ô bên trên rồi bấm Lưu để khởi động lại server.",
            )

        # Lớp 3 - key có gọi được Gemini thật không?
        try:
            with request.urlopen(f"{self.proxy_url}/verify", timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return ProxyStatus(
                False, "error",
                "Proxy sống nhưng không kiểm tra được API key.",
                f"{exc.__class__.__name__}: {exc}",
            )

        status = str(body.get("status", "error"))
        detail = str(body.get("detail", ""))
        model = str(body.get("model", ""))
        provider = str(body.get("provider", ""))
        label = str(body.get("provider_label", "nhà cung cấp AI"))

        if status == "ok":
            return ProxyStatus(True, "ok", f"Kết nối tốt - {label} phản hồi bình thường ({model}).")

        from .providers import PROVIDERS  # tránh import vòng ở đầu module

        signup = PROVIDERS[provider].signup_url if provider in PROVIDERS else ""
        hints = {
            "bad_key": f"Lấy key mới tại {signup}" if signup else "Kiểm tra lại API key.",
            "quota": "Chờ hạn mức reset, nạp thêm tiền, hoặc đổi sang nhà cung cấp khác.",
            "bad_model": f"Đổi tên model ở ô Model (mặc định của {label} thường là an toàn nhất).",
            "network": "Kiểm tra mạng/firewall của máy chạy server.",
            "provider_down": "Máy chủ nhà cung cấp đang lỗi - thử lại sau.",
            "no_key": "Nhập API key vào ô bên trên rồi bấm Lưu.",
        }
        return ProxyStatus(False, status, detail or f"{label} không phản hồi.",
                           hints.get(status, ""))

    def translate_segments(
        self,
        segments: Sequence[Segment],
        source_lang: str,
        target_lang: str,
        reporter: ProgressReporter,
    ) -> List[Segment]:
        """Điền ``translated`` cho từng segment (sửa tại chỗ và trả về list)."""
        texts = [seg.text for seg in segments]
        done = 0
        for start in range(0, len(texts), BATCH_SIZE):
            reporter.check_cancelled()
            batch = texts[start:start + BATCH_SIZE]
            translated = self._post_batch(batch, source_lang, target_lang)
            if len(translated) != len(batch):
                raise PipelineError(
                    f"Proxy trả về {len(translated)} dòng nhưng gửi đi {len(batch)} dòng."
                )
            for offset, line in enumerate(translated):
                segments[start + offset].translated = line.strip()
            done += len(batch)
            reporter.progress(done / max(1, len(texts)))
            reporter.log(f"Đã dịch {done}/{len(texts)} câu.")
        return list(segments)

    def _post_batch(self, lines: Sequence[str], source_lang: str, target_lang: str) -> List[str]:
        payload = json.dumps({
            "lines": list(lines),
            "source_lang": source_lang,
            "target_lang": target_lang,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.license_key:
            headers["X-License-Key"] = self.license_key

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                req = request.Request(
                    f"{self.proxy_url}/translate", data=payload, headers=headers, method="POST"
                )
                with request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                return [str(x) for x in body.get("lines", [])]
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (401, 403):
                    raise PipelineError(f"Proxy từ chối license key ({exc.code}): {detail}") from exc
                last_error = PipelineError(f"Proxy lỗi HTTP {exc.code}: {detail}")
            except Exception as exc:
                last_error = PipelineError(f"Không kết nối được Proxy Server: {exc}")
            time.sleep(2 ** attempt)

        raise last_error or PipelineError("Dịch thuật thất bại không rõ nguyên nhân.")
