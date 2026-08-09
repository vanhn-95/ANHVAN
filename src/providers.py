"""Đa nhà cung cấp AI dịch thuật: OpenAI, Google Gemini, DeepSeek.

Factory Pattern: ``TranslatorAgent.create("openai", key, model)`` trả về đúng agent
cho provider được chọn. Mỗi agent chỉ phải cài đặt ``complete()``; phần dựng prompt,
đếm dòng và phân loại lỗi dùng chung.

Không phụ thuộc SDK riêng của từng hãng - tất cả gọi qua HTTP REST bằng urllib, nên
thêm provider mới không kéo theo dependency mới.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Sequence
from urllib import error, request

DEFAULT_TIMEOUT = 120


@dataclass(frozen=True)
class ProviderSpec:
    """Mô tả một nhà cung cấp: tên hiển thị, model mặc định, nơi lấy key."""

    name: str
    label: str
    default_model: str
    models: List[str]
    env_key: str
    signup_url: str
    note: str = ""


PROVIDERS: Dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        name="gemini",
        label="Google Gemini",
        default_model="gemini-2.5-flash",
        models=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        env_key="GEMINI_API_KEY",
        signup_url="https://aistudio.google.com/apikey",
        note="Có hạn mức miễn phí - phù hợp để bắt đầu.",
    ),
    "openai": ProviderSpec(
        name="openai",
        label="ChatGPT (OpenAI)",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
        env_key="OPENAI_API_KEY",
        signup_url="https://platform.openai.com/api-keys",
        note="Trả phí theo token, không có hạn mức miễn phí.",
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        label="DeepSeek",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
        env_key="DEEPSEEK_API_KEY",
        signup_url="https://platform.deepseek.com/api_keys",
        note="Rẻ nhất trong ba. Lưu ý: model V3 có tên API là 'deepseek-chat'.",
    ),
}

DEFAULT_PROVIDER = "gemini"

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

LANGUAGE_NAMES = {
    "vi": "Vietnamese", "en": "English", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "th": "Thai", "fr": "French", "es": "Spanish",
    "de": "German", "ru": "Russian",
}


class ProviderError(Exception):
    """Lỗi từ nhà cung cấp, kèm mã đã phân loại sẵn."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def language_name(code: str) -> str:
    if code == "auto":
        return "the source language"
    return LANGUAGE_NAMES.get(code, code)


def parse_numbered(raw: str, count: int) -> List[str]:
    """Đọc output `n|text`; dòng nào model bỏ sót thì trả chuỗi rỗng."""
    parsed = {}
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+)\s*\|\s*(.*)", line)
        if match:
            parsed[int(match.group(1))] = match.group(2).strip()
    return [parsed.get(i + 1, "") for i in range(count)]


def classify_http_error(status: int, body: str) -> tuple[str, str]:
    """Quy mã HTTP + nội dung lỗi về mã máy đọc được và câu tiếng Việt."""
    text = body.lower()

    if status in (401, 403) or "api_key_invalid" in text or "api key not valid" in text \
            or "invalid_api_key" in text or "incorrect api key" in text:
        return "bad_key", "API key không hợp lệ hoặc chưa được cấp quyền."
    if status == 429 or "quota" in text or "insufficient_quota" in text \
            or "rate limit" in text or "resource_exhausted" in text:
        return "quota", "API key hết hạn mức (quota) hoặc bị giới hạn tốc độ."
    if status == 404 or "model_not_found" in text or "does not exist" in text:
        return "bad_model", "Tên model không tồn tại hoặc key không được dùng model này."
    if status == 402 or "insufficient balance" in text:
        return "quota", "Tài khoản hết số dư."
    if status >= 500:
        return "provider_down", f"Máy chủ nhà cung cấp đang lỗi (HTTP {status})."
    return "error", f"Lỗi HTTP {status}: {body[:200]}"


def post_json(url: str, payload: dict, headers: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """POST JSON và quy mọi lỗi về ProviderError."""
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST",
                          headers={"Content-Type": "application/json", **headers})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        code, message = classify_http_error(exc.code, body)
        raise ProviderError(code, message) from exc
    except error.URLError as exc:
        raise ProviderError(
            "network", f"Không kết nối được tới nhà cung cấp: {exc.reason}"
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise ProviderError("network", f"Lỗi mạng: {exc}") from exc
    except ValueError as exc:
        raise ProviderError("error", f"Nhà cung cấp trả về dữ liệu không đọc được: {exc}") from exc


# ---------------------------------------------------------------------------- agents
class TranslatorAgent(ABC):
    """Giao diện chung cho mọi nhà cung cấp AI."""

    spec: ProviderSpec = field(init=False)

    def __init__(self, api_key: str, model: str = "") -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or self.spec.default_model

    # --- phần từng provider tự cài đặt ---
    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        """Gửi prompt, trả về text thuần."""

    # --- phần dùng chung ---
    def translate_lines(
        self, lines: Sequence[str], source_lang: str, target_lang: str
    ) -> List[str]:
        """Dịch một lô câu, luôn trả về đúng số dòng đã gửi."""
        if not self.api_key:
            raise ProviderError("no_key", f"Chưa có API key cho {self.spec.label}.")

        payload = "\n".join(f"{i + 1}|{text}" for i, text in enumerate(lines))
        prompt = PROMPT.format(
            source=language_name(source_lang),
            target=language_name(target_lang),
            count=len(lines),
            payload=payload,
        )
        translated = parse_numbered(self.complete(prompt), len(lines))
        # Dòng nào model bỏ sót thì giữ nguyên bản gốc để không lệch timeline.
        return [text or lines[index] for index, text in enumerate(translated)]

    def verify(self) -> tuple[str, str]:
        """Gọi thử một câu cực ngắn. Trả về (mã, mô tả)."""
        if not self.api_key:
            return "no_key", f"Chưa nhập API key cho {self.spec.label}."
        try:
            self.complete("Reply with the single word: ok", max_tokens=8)
        except ProviderError as exc:
            return exc.code, exc.message
        except Exception as exc:
            return "error", f"{exc.__class__.__name__}: {exc}"
        return "ok", f"{self.spec.label} phản hồi bình thường (model {self.model})."

    # --- FACTORY ---
    @staticmethod
    def create(provider: str, api_key: str, model: str = "") -> "TranslatorAgent":
        """Điểm vào duy nhất để dựng agent - thêm provider chỉ cần sửa ở đây."""
        key = (provider or DEFAULT_PROVIDER).strip().lower()
        agents = {
            "gemini": GeminiAgent,
            "openai": OpenAIAgent,
            "deepseek": DeepSeekAgent,
        }
        if key not in agents:
            raise ProviderError(
                "bad_provider",
                f"Không hỗ trợ nhà cung cấp '{provider}'. "
                f"Chọn một trong: {', '.join(agents)}.",
            )
        return agents[key](api_key, model)

    @staticmethod
    def spec_for(provider: str) -> ProviderSpec:
        return PROVIDERS.get((provider or "").strip().lower(), PROVIDERS[DEFAULT_PROVIDER])


class OpenAIAgent(TranslatorAgent):
    """OpenAI Chat Completions. DeepSeek dùng lại nguyên giao thức này."""

    spec = PROVIDERS["openai"]
    base_url = "https://api.openai.com/v1"

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        body = post_json(
            f"{self.base_url}/chat/completions",
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
            {"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("error", f"Phản hồi lạ từ {self.spec.label}: {body}") from exc


class DeepSeekAgent(OpenAIAgent):
    """DeepSeek dùng API tương thích OpenAI, chỉ khác base URL."""

    spec = PROVIDERS["deepseek"]
    base_url = "https://api.deepseek.com/v1"

    # Tên thương mại người dùng hay gõ -> tên model thật của API.
    ALIASES = {
        "deepseek-v3": "deepseek-chat",
        "deepseek-v3.1": "deepseek-chat",
        "deepseek-r1": "deepseek-reasoner",
    }

    def __init__(self, api_key: str, model: str = "") -> None:
        super().__init__(api_key, model)
        self.model = self.ALIASES.get(self.model.lower(), self.model)


class GeminiAgent(TranslatorAgent):
    """Google Gemini qua REST generativelanguage."""

    spec = PROVIDERS["gemini"]
    base_url = "https://generativelanguage.googleapis.com/v1beta"

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        body = post_json(
            f"{self.base_url}/models/{self.model}:generateContent",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": max_tokens},
            },
            {"x-goog-api-key": self.api_key},
        )
        try:
            parts = body["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            # Bị chặn bởi bộ lọc an toàn cũng rơi vào nhánh này.
            blocked = body.get("promptFeedback", {}).get("blockReason")
            if blocked:
                raise ProviderError("blocked", f"Gemini chặn nội dung: {blocked}") from exc
            raise ProviderError("error", f"Phản hồi lạ từ Gemini: {body}") from exc
