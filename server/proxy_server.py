"""FastAPI proxy dịch thuật qua Gemini.

Client không bao giờ giữ GEMINI_API_KEY: nó chỉ gửi danh sách câu thoại kèm
license key, server dịch rồi trả về đúng số dòng theo đúng thứ tự.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# Danh sách license hợp lệ, phân tách bởi dấu phẩy. Để trống = không kiểm tra.
ALLOWED_LICENSES = {k.strip() for k in os.environ.get("SUBAI_LICENSES", "").split(",") if k.strip()}
MAX_LINES = 100


def model_name() -> str:
    """Đọc lúc gọi chứ không cache, để restart server là ăn ngay giá trị mới."""
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()

app = FastAPI(title="SubAI Translation Proxy", version="1.0.0")

LANGUAGE_NAMES = {
    "vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "th": "Thai", "fr": "French", "es": "Spanish",
    "de": "German", "ru": "Russian",
}

PROMPT = """You are a professional subtitle translator.
Translate each numbered line from {source} into {target}.

Rules:
- Keep the speaker's tone, register and style. Natural spoken language, not literal.
- Keep it short enough to be spoken in the same amount of time as the original.
- Do NOT merge, split, reorder or drop lines.
- Output EXACTLY {count} lines, each prefixed with its number and a pipe, like `1|text`.
- No commentary, no markdown, no empty lines.

Lines:
{payload}"""


class TranslateRequest(BaseModel):
    lines: List[str] = Field(..., min_length=1, max_length=MAX_LINES)
    source_lang: str = "auto"
    target_lang: str = "vi"


class TranslateResponse(BaseModel):
    lines: List[str]
    model: str


def _language_name(code: str) -> str:
    if code == "auto":
        return "the source language"
    return LANGUAGE_NAMES.get(code, code)


def _check_license(license_key: Optional[str]) -> None:
    if not ALLOWED_LICENSES:
        return
    if not license_key or license_key not in ALLOWED_LICENSES:
        raise HTTPException(status_code=403, detail="License key không hợp lệ.")


def _parse_numbered(raw: str, count: int) -> List[str]:
    """Đọc lại output `n|text`; dòng nào thiếu thì trả chuỗi rỗng."""
    parsed = {}
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+)\s*\|\s*(.*)", line)
        if match:
            parsed[int(match.group(1))] = match.group(2).strip()
    return [parsed.get(i + 1, "") for i in range(count)]


def classify_gemini_error(exc: Exception) -> tuple[str, str]:
    """Quy lỗi của Gemini về mã máy đọc được + câu tiếng Việt cho người dùng."""
    text = f"{exc.__class__.__name__}: {exc}".lower()

    if any(hint in text for hint in ("api_key_invalid", "api key not valid", "unauthenticated",
                                     "invalid authentication", "401", "403", "permission_denied")):
        return "bad_key", "API key không hợp lệ hoặc chưa bật quyền cho Gemini API."
    if any(hint in text for hint in ("resource_exhausted", "quota", "rate limit", "429")):
        return "quota", "API key hết hạn mức (quota) hoặc bị giới hạn tốc độ."
    if any(hint in text for hint in ("not found", "404", "unsupported model")):
        return "bad_model", f"Model '{model_name()}' không tồn tại hoặc key không được dùng model này."
    if any(hint in text for hint in ("timeout", "connection", "network", "dns", "unreachable")):
        return "network", "Server không kết nối được tới Google. Kiểm tra mạng/proxy/firewall."
    return "error", f"Gemini báo lỗi: {exc}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": model_name(), "api_key_configured": bool(api_key())}


@app.get("/verify")
def verify() -> dict:
    """Gọi thử Gemini một câu ngắn để biết key có dùng được thật không.

    Trả về status: ok | no_key | bad_key | quota | bad_model | network | error
    """
    if not api_key():
        return {
            "status": "no_key",
            "detail": "Server chưa được cấu hình GEMINI_API_KEY.",
            "model": model_name(),
        }

    try:
        from google import genai  # noqa: PLC0415
    except ImportError:
        return {
            "status": "error",
            "detail": "Server thiếu thư viện google-genai (pip install google-genai).",
            "model": model_name(),
        }

    try:
        client = genai.Client(api_key=api_key())
        client.models.generate_content(model=model_name(), contents="ping")
    except Exception as exc:
        status, detail = classify_gemini_error(exc)
        return {"status": status, "detail": detail, "model": model_name()}

    return {"status": "ok", "detail": "API key hợp lệ, gọi Gemini thành công.",
            "model": model_name()}


@app.post("/translate", response_model=TranslateResponse)
def translate(
    request: TranslateRequest,
    x_license_key: Optional[str] = Header(default=None, alias="X-License-Key"),
) -> TranslateResponse:
    _check_license(x_license_key)
    if not api_key():
        raise HTTPException(status_code=500, detail="Server chưa cấu hình GEMINI_API_KEY.")

    try:
        from google import genai  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Server thiếu google-genai.") from exc

    payload = "\n".join(f"{i + 1}|{text}" for i, text in enumerate(request.lines))
    prompt = PROMPT.format(
        source=_language_name(request.source_lang),
        target=_language_name(request.target_lang),
        count=len(request.lines),
        payload=payload,
    )

    try:
        client = genai.Client(api_key=api_key())
        response = client.models.generate_content(model=model_name(), contents=prompt)
        text = response.text or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini lỗi: {exc}") from exc

    translated = _parse_numbered(text, len(request.lines))
    # Dòng nào model bỏ sót thì giữ nguyên bản gốc để không lệch timeline.
    translated = [t or request.lines[i] for i, t in enumerate(translated)]
    return TranslateResponse(lines=translated, model=model_name())
