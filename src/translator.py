"""Client gọi Proxy Server dịch thuật (Gemini nằm phía server)."""

from __future__ import annotations

import json
import time
from typing import List, Sequence
from urllib import error, request

from .progress import ProgressReporter
from .utils import PipelineError, Segment

BATCH_SIZE = 40
MAX_RETRIES = 3


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
