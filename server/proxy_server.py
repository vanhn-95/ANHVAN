"""FastAPI proxy dịch thuật đa nhà cung cấp (Gemini / OpenAI / DeepSeek).

Client không bao giờ giữ API key: nó chỉ gửi danh sách câu thoại kèm license key,
server dịch rồi trả về đúng số dòng theo đúng thứ tự.

Provider, key và model đọc từ biến môi trường ngay lúc gọi (không cache), nên app
chỉ cần restart tiến trình server là ăn cấu hình mới.
"""

from __future__ import annotations

import os
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.providers import (
    PROVIDERS,
    ProviderError,
    TranslatorAgent,
    parse_numbered,
)

# Danh sách license hợp lệ, phân tách bởi dấu phẩy. Để trống = không kiểm tra.
ALLOWED_LICENSES = {k.strip() for k in os.environ.get("SUBAI_LICENSES", "").split(",") if k.strip()}
MAX_LINES = 100

app = FastAPI(title="SubAI Translation Proxy", version="1.1.0")


def provider_name() -> str:
    name = os.environ.get("SUBAI_PROVIDER", "gemini").strip().lower()
    return name if name in PROVIDERS else "gemini"


def api_key() -> str:
    """Key của provider đang chọn; vẫn chấp nhận biến riêng của từng hãng."""
    explicit = os.environ.get("SUBAI_API_KEY", "").strip()
    if explicit:
        return explicit
    return os.environ.get(PROVIDERS[provider_name()].env_key, "").strip()


def model_name() -> str:
    return (
        os.environ.get("SUBAI_MODEL", "").strip()
        or PROVIDERS[provider_name()].default_model
    )


def build_agent() -> TranslatorAgent:
    return TranslatorAgent.create(provider_name(), api_key(), model_name())


class TranslateRequest(BaseModel):
    lines: List[str] = Field(..., min_length=1, max_length=MAX_LINES)
    source_lang: str = "auto"
    target_lang: str = "vi"


class TranslateResponse(BaseModel):
    lines: List[str]
    model: str
    provider: str


def _check_license(license_key: Optional[str]) -> None:
    if not ALLOWED_LICENSES:
        return
    if not license_key or license_key not in ALLOWED_LICENSES:
        raise HTTPException(status_code=403, detail="License key không hợp lệ.")


# Giữ tên cũ cho code/test đã tham chiếu.
_parse_numbered = parse_numbered


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": provider_name(),
        "provider_label": PROVIDERS[provider_name()].label,
        "model": model_name(),
        "api_key_configured": bool(api_key()),
        "providers": sorted(PROVIDERS),
    }


@app.get("/verify")
def verify() -> dict:
    """Gọi thử nhà cung cấp một câu ngắn để biết key có dùng được thật không.

    status: ok | no_key | bad_key | quota | bad_model | network | provider_down | error
    """
    status, detail = build_agent().verify()
    return {
        "status": status,
        "detail": detail,
        "provider": provider_name(),
        "provider_label": PROVIDERS[provider_name()].label,
        "model": model_name(),
    }


@app.post("/translate", response_model=TranslateResponse)
def translate(
    request: TranslateRequest,
    x_license_key: Optional[str] = Header(default=None, alias="X-License-Key"),
) -> TranslateResponse:
    _check_license(x_license_key)

    try:
        lines = build_agent().translate_lines(
            request.lines, request.source_lang, request.target_lang
        )
    except ProviderError as exc:
        status = 403 if exc.code in ("bad_key", "no_key") else 502
        raise HTTPException(status_code=status, detail=f"[{exc.code}] {exc.message}") from exc

    return TranslateResponse(lines=lines, model=model_name(), provider=provider_name())
