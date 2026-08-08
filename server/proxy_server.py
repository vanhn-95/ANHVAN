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

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Danh sách license hợp lệ, phân tách bởi dấu phẩy. Để trống = không kiểm tra.
ALLOWED_LICENSES = {k.strip() for k in os.environ.get("SUBAI_LICENSES", "").split(",") if k.strip()}
MAX_LINES = 100

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME, "api_key_configured": bool(API_KEY)}


@app.post("/translate", response_model=TranslateResponse)
def translate(
    request: TranslateRequest,
    x_license_key: Optional[str] = Header(default=None, alias="X-License-Key"),
) -> TranslateResponse:
    _check_license(x_license_key)
    if not API_KEY:
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
        client = genai.Client(api_key=API_KEY)
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = response.text or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini lỗi: {exc}") from exc

    translated = _parse_numbered(text, len(request.lines))
    # Dòng nào model bỏ sót thì giữ nguyên bản gốc để không lệch timeline.
    translated = [t or request.lines[i] for i, t in enumerate(translated)]
    return TranslateResponse(lines=translated, model=MODEL_NAME)
