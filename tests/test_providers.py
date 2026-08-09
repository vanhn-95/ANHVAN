"""Test factory đa nhà cung cấp.

Mạng thật bị chặn trong CI nên OpenAI/DeepSeek/Gemini được kiểm bằng một HTTP
server giả nói đúng giao thức của từng hãng: xác minh đúng URL, đúng header xác
thực, đúng hình dạng request/response và đúng phân loại lỗi.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.providers import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    DeepSeekAgent,
    GeminiAgent,
    OpenAIAgent,
    ProviderError,
    TranslatorAgent,
    classify_http_error,
    parse_numbered,
)


class FakeProviderServer:
    """HTTP server giả, ghi lại request cuối và trả về phản hồi đặt sẵn."""

    def __init__(self):
        self.last_path = None
        self.last_headers = {}
        self.last_body = {}
        self.status = 200
        self.response = {}

        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                server.last_path = self.path
                # Giữ nguyên object của http.server: nó tra header không phân biệt
                # hoa/thường, còn urllib thì chuẩn hoá tên header khi gửi đi.
                server.last_headers = self.headers
                server.last_body = json.loads(self.rfile.read(length) or b"{}")

                payload = json.dumps(server.response).encode()
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake():
    server = FakeProviderServer()
    yield server
    server.stop()


def openai_reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def gemini_reply(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class TestFactory:
    @pytest.mark.parametrize("name,expected", [
        ("gemini", GeminiAgent), ("openai", OpenAIAgent), ("deepseek", DeepSeekAgent),
    ])
    def test_creates_right_agent(self, name, expected):
        assert isinstance(TranslatorAgent.create(name, "k"), expected)

    def test_case_insensitive(self):
        assert isinstance(TranslatorAgent.create("OpenAI", "k"), OpenAIAgent)

    def test_default_model_per_provider(self):
        assert TranslatorAgent.create("openai", "k").model == "gpt-4o"
        assert TranslatorAgent.create("deepseek", "k").model == "deepseek-chat"
        assert TranslatorAgent.create("gemini", "k").model == "gemini-2.5-flash"

    def test_explicit_model_wins(self):
        assert TranslatorAgent.create("openai", "k", "gpt-4o").model == "gpt-4o"

    def test_blank_model_falls_back_to_default(self):
        assert TranslatorAgent.create("openai", "k", "   ").model == "gpt-4o"

    def test_unknown_provider_raises(self):
        with pytest.raises(ProviderError) as exc:
            TranslatorAgent.create("claude-3", "k")
        assert exc.value.code == "bad_provider"

    def test_empty_provider_uses_default(self):
        assert TranslatorAgent.create("", "k").spec.name == DEFAULT_PROVIDER

    def test_deepseek_reuses_openai_protocol(self):
        assert issubclass(DeepSeekAgent, OpenAIAgent)
        assert DeepSeekAgent.base_url != OpenAIAgent.base_url

    def test_every_provider_has_complete_spec(self):
        for name, spec in PROVIDERS.items():
            assert spec.name == name
            assert spec.default_model and spec.models
            assert spec.env_key.endswith("_API_KEY")
            assert spec.signup_url.startswith("https://")


class TestOpenAIProtocol:
    def test_request_shape_and_auth(self, fake):
        agent = OpenAIAgent("sk-test-123", "gpt-4o")
        agent.base_url = fake.url
        fake.response = openai_reply("1|Xin chào")

        agent.complete("dịch đi")

        assert fake.last_path == "/chat/completions"
        assert fake.last_headers["Authorization"] == "Bearer sk-test-123"
        assert fake.last_body["model"] == "gpt-4o"
        assert fake.last_body["messages"][0]["content"] == "dịch đi"

    def test_reads_content(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("kết quả")
        assert agent.complete("x") == "kết quả"

    def test_deepseek_hits_its_own_path(self, fake):
        agent = DeepSeekAgent("k", "deepseek-chat")
        agent.base_url = fake.url
        fake.response = openai_reply("ok")
        agent.complete("x")
        assert fake.last_body["model"] == "deepseek-chat"

    def test_malformed_response_raises(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = {"khong": "dung dinh dang"}
        with pytest.raises(ProviderError) as exc:
            agent.complete("x")
        assert exc.value.code == "error"


class TestGeminiProtocol:
    def test_request_shape_and_auth(self, fake):
        agent = GeminiAgent("AIza-test", "gemini-2.5-pro")
        agent.base_url = fake.url
        fake.response = gemini_reply("xong")

        agent.complete("dịch đi")

        assert fake.last_path == "/models/gemini-2.5-pro:generateContent"
        assert fake.last_headers["x-goog-api-key"] == "AIza-test"
        assert fake.last_body["contents"][0]["parts"][0]["text"] == "dịch đi"

    def test_joins_multiple_parts(self, fake):
        agent = GeminiAgent("k")
        agent.base_url = fake.url
        fake.response = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
        assert agent.complete("x") == "ab"

    def test_safety_block_reported(self, fake):
        agent = GeminiAgent("k")
        agent.base_url = fake.url
        fake.response = {"promptFeedback": {"blockReason": "SAFETY"}}
        with pytest.raises(ProviderError) as exc:
            agent.complete("x")
        assert exc.value.code == "blocked"


class TestErrorsAcrossProviders:
    @pytest.mark.parametrize("status,code", [
        (401, "bad_key"), (403, "bad_key"), (429, "quota"),
        (404, "bad_model"), (402, "quota"), (500, "provider_down"),
    ])
    def test_http_status_mapped(self, fake, status, code):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.status = status
        fake.response = {"error": "chi tiết"}

        with pytest.raises(ProviderError) as exc:
            agent.complete("x")
        assert exc.value.code == code

    def test_verify_returns_code_not_exception(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.status = 401
        fake.response = {"error": "no"}

        code, detail = agent.verify()
        assert code == "bad_key"
        assert detail

    def test_verify_ok(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("ok")

        code, detail = agent.verify()
        assert code == "ok"
        assert "gpt-4o" in detail

    def test_verify_without_key_never_calls_network(self, fake):
        agent = OpenAIAgent("")
        agent.base_url = fake.url
        assert agent.verify()[0] == "no_key"
        assert fake.last_path is None

    def test_unreachable_host_is_network(self):
        agent = OpenAIAgent("k")
        agent.base_url = "http://127.0.0.1:1"
        with pytest.raises(ProviderError) as exc:
            agent.complete("x")
        assert exc.value.code == "network"


class TestTranslateLines:
    def test_returns_same_number_of_lines(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("1|Xin chào\n2|Tạm biệt")

        result = agent.translate_lines(["Hello", "Bye"], "en", "vi")
        assert result == ["Xin chào", "Tạm biệt"]

    def test_missing_line_keeps_original(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("1|Xin chào")

        result = agent.translate_lines(["Hello", "Bye"], "en", "vi")
        assert result == ["Xin chào", "Bye"]

    def test_prompt_carries_language_names(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("1|a")

        agent.translate_lines(["x"], "ja", "vi")
        prompt = fake.last_body["messages"][0]["content"]
        assert "Japanese" in prompt and "Vietnamese" in prompt

    def test_auto_source_language(self, fake):
        agent = OpenAIAgent("k")
        agent.base_url = fake.url
        fake.response = openai_reply("1|a")

        agent.translate_lines(["x"], "auto", "vi")
        assert "the source language" in fake.last_body["messages"][0]["content"]

    def test_no_key_raises_before_network(self, fake):
        agent = OpenAIAgent("")
        agent.base_url = fake.url
        with pytest.raises(ProviderError) as exc:
            agent.translate_lines(["x"], "en", "vi")
        assert exc.value.code == "no_key"
        assert fake.last_path is None


class TestParseNumbered:
    def test_basic(self):
        assert parse_numbered("1|a\n2|b", 2) == ["a", "b"]

    def test_missing_becomes_empty(self):
        assert parse_numbered("1|a", 2) == ["a", ""]

    def test_ignores_prose(self):
        assert parse_numbered("Bản dịch:\n1|a\nHết", 1) == ["a"]


class TestClassifier:
    def test_body_hint_beats_status(self):
        assert classify_http_error(400, "API_KEY_INVALID")[0] == "bad_key"

    def test_messages_are_vietnamese(self):
        for status in (401, 429, 404):
            _, message = classify_http_error(status, "")
            assert any(ch in message for ch in "ăâđêôơư")


class TestDeepSeekAliases:
    """Tên người dùng hay gõ phải map sang tên model thật của API."""

    @pytest.mark.parametrize("typed,real", [
        ("deepseek-v3", "deepseek-chat"),
        ("deepseek-V3", "deepseek-chat"),
        ("deepseek-r1", "deepseek-reasoner"),
        ("deepseek-chat", "deepseek-chat"),
        ("deepseek-reasoner", "deepseek-reasoner"),
    ])
    def test_alias_resolution(self, typed, real):
        assert TranslatorAgent.create("deepseek", "k", typed).model == real

    def test_alias_used_in_actual_request(self, fake):
        agent = TranslatorAgent.create("deepseek", "k", "deepseek-v3")
        agent.base_url = fake.url
        fake.response = openai_reply("ok")
        agent.complete("x")
        assert fake.last_body["model"] == "deepseek-chat"

    def test_every_suggested_model_is_callable(self, fake):
        """Mọi model hiện trong dropdown phải gọi được, không cái nào 404 vì tên sai."""
        for name in PROVIDERS["deepseek"].models:
            agent = TranslatorAgent.create("deepseek", "k", name)
            assert agent.model in ("deepseek-chat", "deepseek-reasoner")
