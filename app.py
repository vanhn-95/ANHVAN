"""
Chuyển đổi Giọng nói — Speech-to-Text phân tích cuộc gọi.

Ứng dụng web hiển thị bản ghi cuộc gọi dưới dạng khung chat đối thoại,
tự động tách hai người nói (speaker diarization).

Chạy cục bộ:      python app.py
Hugging Face:     Space tự chạy file này (sdk: gradio, app_file: app.py)
"""

from __future__ import annotations

import html
import logging
import os
import time
from dataclasses import dataclass

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("stt")


# --------------------------------------------------------------------------- #
# Cấu hình (trên Hugging Face: đặt ở tab Settings → Variables and secrets)
# --------------------------------------------------------------------------- #


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        log.warning("Biến %s không phải số, dùng mặc định %s", name, default)
        return default


DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")
GROQ_MODEL = os.getenv("GROQ_MODEL", "whisper-large-v3-turbo")

# Chạy nhiều người cùng lúc: công việc chủ yếu là chờ mạng nên thread rất rẻ.
CONCURRENCY_LIMIT = _env_int("CONCURRENCY_LIMIT", 8)
QUEUE_MAX_SIZE = _env_int("QUEUE_MAX_SIZE", 40)

MAX_FILE_MB = _env_int("MAX_FILE_MB", 100)
GROQ_MAX_MB = 25  # giới hạn cứng phía Groq

REQUEST_TIMEOUT = (10, _env_int("READ_TIMEOUT", 300))  # (connect, read)
MAX_RETRIES = _env_int("MAX_RETRIES", 3)
RETRY_STATUS = {429, 500, 502, 503, 504}

# Xoá file ghi âm khỏi máy chủ ngay sau khi bóc băng xong (dữ liệu nhạy cảm).
DELETE_UPLOAD_AFTER = os.getenv("DELETE_UPLOAD_AFTER", "1") not in {"0", "false", "False"}

IS_SPACE = bool(os.getenv("SPACE_ID"))

LABEL_AGENT = "THẨM ĐỊNH VIÊN"
LABEL_CUSTOMER = "KHÁCH HÀNG"
LEGEND_AGENT = "Thẩm định viên"
LEGEND_CUSTOMER = "Khách hàng"

ACCEPTED_EXTS = [".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac", ".webm", ".aac"]

MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


# --------------------------------------------------------------------------- #
# Mô hình dữ liệu
# --------------------------------------------------------------------------- #


@dataclass
class Turn:
    """Một lượt thoại đã gộp của cùng một người nói."""

    speaker: int
    start: float
    text: str


@dataclass
class Result:
    turns: list[Turn]
    duration: float  # thời lượng audio (giây), 0 nếu nhà cung cấp không trả về


class TranscriptionError(Exception):
    """Lỗi có thông điệp tiếng Việt, hiển thị thẳng cho người dùng."""


# --------------------------------------------------------------------------- #
# Gọi API
# --------------------------------------------------------------------------- #


def _guess_mime(path: str) -> str:
    return MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _post_with_retry(build_request, provider: str) -> requests.Response:
    """Gọi API, thử lại khi gặp lỗi tạm thời (429 / 5xx / timeout).

    `build_request` được gọi lại ở mỗi lần thử để mở lại file — stream đã đọc
    một lần thì không tua lại được.
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = build_request()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            log.warning("%s: lỗi mạng lần %d/%d: %s", provider, attempt, MAX_RETRIES, exc)
        else:
            if response.status_code not in RETRY_STATUS:
                return response
            last_error = None
            log.warning(
                "%s: HTTP %d lần %d/%d", provider, response.status_code, attempt, MAX_RETRIES
            )
            if attempt == MAX_RETRIES:
                return response

        time.sleep(2 ** (attempt - 1))

    if isinstance(last_error, requests.exceptions.Timeout):
        raise TranscriptionError(
            f"{provider} không phản hồi kịp. File có thể quá dài — hãy thử lại sau ít phút."
        )
    raise TranscriptionError(f"Không kết nối được tới {provider}. Vui lòng thử lại.")


def _fail_on_error(response: requests.Response, provider: str, key_name: str) -> None:
    if response.ok:
        return

    # Không đưa nội dung thô của nhà cung cấp ra giao diện; chỉ ghi vào log.
    log.error("%s HTTP %d: %s", provider, response.status_code, response.text[:500])

    if response.status_code in (401, 403):
        raise TranscriptionError(
            f"{key_name} không hợp lệ hoặc đã hết hạn. Vui lòng báo quản trị viên."
        )
    if response.status_code == 429:
        raise TranscriptionError(
            f"{provider} đang quá tải hoặc đã hết hạn mức. Vui lòng thử lại sau ít phút."
        )
    if response.status_code == 413:
        raise TranscriptionError(f"File vượt quá giới hạn dung lượng của {provider}.")
    if response.status_code >= 500:
        raise TranscriptionError(f"{provider} đang gặp sự cố. Vui lòng thử lại sau ít phút.")
    raise TranscriptionError(f"{provider} từ chối yêu cầu (mã {response.status_code}).")


def transcribe_deepgram(path: str, language: str) -> Result:
    """Deepgram Nova-2 — diarization gốc, trả về utterances đã tách người nói."""
    params = {
        "model": DEEPGRAM_MODEL,
        "language": language,
        "diarize": "true",
        "punctuate": "true",
        "smart_format": "true",
        "utterances": "true",
        "filler_words": "false",
    }

    def build():
        with open(path, "rb") as fh:
            return requests.post(
                DEEPGRAM_URL,
                params=params,
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": _guess_mime(path),
                },
                data=fh,
                timeout=REQUEST_TIMEOUT,
            )

    response = _post_with_retry(build, "Deepgram")
    _fail_on_error(response, "Deepgram", "DEEPGRAM_API_KEY")

    payload = response.json()
    results = payload.get("results", {}) or {}
    duration = float((payload.get("metadata", {}) or {}).get("duration", 0.0) or 0.0)
    utterances = results.get("utterances") or []

    if not utterances:
        channels = results.get("channels") or []
        alternatives = channels[0].get("alternatives") if channels else None
        flat = (alternatives[0].get("transcript") if alternatives else "") or ""
        turns = [Turn(0, 0.0, flat.strip())] if flat.strip() else []
        return Result(turns, duration)

    segments = [
        Turn(
            speaker=int(item.get("speaker", 0) or 0),
            start=float(item.get("start", 0.0) or 0.0),
            text=(item.get("transcript") or "").strip(),
        )
        for item in utterances
    ]
    return Result([s for s in segments if s.text], duration)


def transcribe_groq(path: str, language: str) -> Result:
    """Groq Whisper — rất nhanh nhưng KHÔNG có diarization gốc.

    Người nói được suy đoán theo khoảng lặng giữa các đoạn, chỉ mang tính
    tương đối. Dùng Deepgram khi cần tách vai chính xác.
    """

    def build():
        with open(path, "rb") as fh:
            return requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (os.path.basename(path), fh, _guess_mime(path))},
                data={
                    "model": GROQ_MODEL,
                    "language": language,
                    "response_format": "verbose_json",
                    "temperature": "0",
                },
                timeout=REQUEST_TIMEOUT,
            )

    response = _post_with_retry(build, "Groq")
    _fail_on_error(response, "Groq", "GROQ_API_KEY")

    payload = response.json()
    duration = float(payload.get("duration", 0.0) or 0.0)
    segments = payload.get("segments") or []

    if not segments:
        flat = (payload.get("text") or "").strip()
        return Result([Turn(0, 0.0, flat)] if flat else [], duration)

    gap_threshold = 0.9
    turns: list[Turn] = []
    speaker = 0
    previous_end = None

    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0) or 0.0)
        if previous_end is not None and (start - previous_end) > gap_threshold:
            speaker = 1 - speaker
        turns.append(Turn(speaker, start, text))
        previous_end = float(segment.get("end", start) or start)

    return Result(turns, duration)


# --------------------------------------------------------------------------- #
# Xử lý kết quả
# --------------------------------------------------------------------------- #


def merge_turns(segments: list[Turn]) -> list[Turn]:
    """Gộp các đoạn liên tiếp của cùng một người thành một lượt thoại."""
    merged: list[Turn] = []
    for segment in segments:
        if merged and merged[-1].speaker == segment.speaker:
            merged[-1].text = f"{merged[-1].text} {segment.text}".strip()
        else:
            merged.append(Turn(segment.speaker, segment.start, segment.text))
    return merged


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def role_of(speaker: int, swap: bool) -> str:
    """Mặc định: Speaker 0 = khách hàng (trái), Speaker 1 = thẩm định viên (phải)."""
    is_agent = speaker != 0
    if swap:
        is_agent = not is_agent
    return "agent" if is_agent else "customer"


def render_chat(turns: list[Turn], swap: bool) -> str:
    bubbles = []
    for turn in turns:
        role = role_of(turn.speaker, swap)
        label = LABEL_AGENT if role == "agent" else LABEL_CUSTOMER
        bubbles.append(
            f'<div class="stt-row stt-{role}">'
            f'<div class="stt-bubble">'
            f'<div class="stt-meta"><span class="stt-name">{label}</span>'
            f'<span class="stt-time">{format_timestamp(turn.start)}</span></div>'
            f'<div class="stt-text">{html.escape(turn.text)}</div>'
            f"</div></div>"
        )

    return (
        '<div class="stt-chat-wrap">'
        f'<div class="stt-chat">{"".join(bubbles)}</div>'
        '<div class="stt-legend">'
        f'<span class="stt-legend-item"><span class="stt-dot stt-dot-agent"></span>{LEGEND_AGENT}</span>'
        f'<span class="stt-legend-item"><span class="stt-dot stt-dot-customer"></span>{LEGEND_CUSTOMER}</span>'
        "</div></div>"
    )


def render_result_header(count: int) -> str:
    return f'<div class="stt-result-title">Chi tiết cuộc gọi ({count} lượt thoại)</div>'


def to_plain_text(turns: list[Turn], swap: bool) -> str:
    return "\n".join(
        f"[{format_timestamp(t.start)}] "
        f"{LABEL_AGENT if role_of(t.speaker, swap) == 'agent' else LABEL_CUSTOMER}: {t.text}"
        for t in turns
    )


# --------------------------------------------------------------------------- #
# Engine khả dụng
# --------------------------------------------------------------------------- #

ENGINE_CHOICES: list[tuple[str, str]] = []
if DEEPGRAM_API_KEY:
    ENGINE_CHOICES.append(("Deepgram Nova-2 — tách người nói chính xác", "deepgram"))
if GROQ_API_KEY:
    ENGINE_CHOICES.append(("Groq Whisper — nhanh nhất, tách người nói tương đối", "groq"))

DEFAULT_ENGINE = ENGINE_CHOICES[0][1] if ENGINE_CHOICES else "deepgram"

if not ENGINE_CHOICES:
    log.error("Chưa cấu hình DEEPGRAM_API_KEY hoặc GROQ_API_KEY — ứng dụng sẽ báo lỗi khi phân tích.")
else:
    log.info("Engine khả dụng: %s", ", ".join(value for _, value in ENGINE_CHOICES))


# --------------------------------------------------------------------------- #
# Handler chính
# --------------------------------------------------------------------------- #


def analyze(file_path: str | None, engine: str, language: str, swap: bool, request: gr.Request):
    """Trả về: chat_html, header_html, raw_text, status, upload_screen, result_screen."""
    client = getattr(request, "session_hash", "?") if request else "?"

    def fail(message: str):
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            f'<div class="stt-status stt-error">{html.escape(message)}</div>',
            gr.update(visible=True),
            gr.update(visible=False),
        )

    if not ENGINE_CHOICES:
        return fail(
            "Máy chủ chưa được cấu hình API key. Quản trị viên cần thêm "
            "DEEPGRAM_API_KEY hoặc GROQ_API_KEY vào phần Secrets."
        )
    if not file_path:
        return fail("Vui lòng chọn một file ghi âm trước khi phân tích.")
    if not os.path.exists(file_path):
        return fail("File tải lên đã hết hạn trên máy chủ. Vui lòng tải lên lại.")

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ACCEPTED_EXTS:
        return fail(
            f"Định dạng {ext or 'không xác định'} chưa được hỗ trợ. Hãy dùng .mp3, .wav hoặc .m4a."
        )

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        return fail(f"File nặng {size_mb:.0f}MB, vượt giới hạn {MAX_FILE_MB}MB của hệ thống.")

    engine = engine if engine in {value for _, value in ENGINE_CHOICES} else DEFAULT_ENGINE
    if engine == "groq" and size_mb > GROQ_MAX_MB:
        return fail(
            f"File nặng {size_mb:.0f}MB, vượt giới hạn {GROQ_MAX_MB}MB của Groq. "
            "Hãy chọn Deepgram hoặc nén file lại."
        )

    log.info("[%s] bắt đầu: %.1fMB, engine=%s, lang=%s", client, size_mb, engine, language)
    started = time.perf_counter()

    try:
        result = (
            transcribe_deepgram(file_path, language)
            if engine == "deepgram"
            else transcribe_groq(file_path, language)
        )
    except TranscriptionError as exc:
        log.warning("[%s] thất bại: %s", client, exc)
        return fail(str(exc))
    except ValueError:  # JSON hỏng
        log.exception("[%s] phản hồi không phải JSON hợp lệ", client)
        return fail("Máy chủ nhận dạng trả về dữ liệu không hợp lệ. Vui lòng thử lại.")
    except Exception:
        log.exception("[%s] lỗi không lường trước", client)
        return fail("Đã xảy ra lỗi ngoài dự kiến. Vui lòng thử lại sau ít phút.")

    elapsed = time.perf_counter() - started
    turns = merge_turns(result.turns)

    if not turns:
        # Giữ lại file: người dùng có thể chọn lại ngôn ngữ rồi thử lần nữa.
        log.info("[%s] không có nội dung sau %.1fs", client, elapsed)
        return fail(
            "Không nhận được nội dung nào từ file này. "
            "File có thể bị lỗi, không có tiếng nói, hoặc sai ngôn ngữ đã chọn."
        )

    log.info("[%s] xong: %d lượt thoại, %.1fs", client, len(turns), elapsed)

    # Chỉ xoá khi đã bóc băng thành công — nếu lỗi thì giữ lại để thử lại
    # mà không phải tải lên từ đầu. Phần còn lại do delete_cache dọn định kỳ.
    if DELETE_UPLOAD_AFTER:
        _safe_remove(file_path, client)

    engine_name = (
        f"Deepgram {DEEPGRAM_MODEL}" if engine == "deepgram" else f"Groq {GROQ_MODEL}"
    )
    duration_note = (
        f" · thời lượng {format_timestamp(result.duration)}" if result.duration else ""
    )
    status = (
        f'<div class="stt-status stt-ok">Hoàn tất trong <b>{elapsed:.1f}s</b>'
        f"{duration_note} · {engine_name}</div>"
    )

    return (
        render_chat(turns, swap),
        render_result_header(len(turns)),
        to_plain_text(turns, swap),
        status,
        gr.update(visible=False),
        gr.update(visible=True),
    )


def _safe_remove(path: str, client: str) -> None:
    """Xoá file ghi âm khỏi máy chủ — bản ghi cuộc gọi là dữ liệu nhạy cảm."""
    try:
        os.remove(path)
        log.info("[%s] đã xoá file tải lên", client)
    except OSError as exc:
        log.warning("[%s] không xoá được file tải lên: %s", client, exc)


def reset():
    """Quay về màn hình upload ban đầu."""
    return (
        None,
        "",
        "",
        "",
        "",
        gr.update(visible=True),
        gr.update(visible=False),
    )


# --------------------------------------------------------------------------- #
# Giao diện
# --------------------------------------------------------------------------- #

CSS = """
:root {
  --stt-agent-from: #4f46e5;
  --stt-agent-to:   #7c3aed;
  --stt-customer:   #f4f5f7;
  --stt-border:     #e5e7eb;
  --stt-ink:        #111827;
  --stt-muted:      #6b7280;
}

.gradio-container { max-width: 900px !important; margin: 0 auto !important; }
footer { display: none !important; }

/* ----- Header ----- */
.stt-header { text-align: center; padding: 28px 0 12px; }
.stt-header h1 {
  font-size: 30px; font-weight: 700; margin: 0 0 6px;
  color: var(--stt-agent-from);
}
.stt-header p { font-size: 15px; color: var(--stt-muted); margin: 0; }

/* ----- Upload ----- */
.stt-card {
  border: 1px solid var(--stt-border); border-radius: 16px;
  padding: 18px; background: #fff;
}
.stt-hint { font-size: 13px; color: var(--stt-muted); text-align: center; margin-top: 10px; }
.stt-hidden { display: none !important; }

.stt-status { text-align: center; font-size: 14px; padding: 8px 0; min-height: 8px; }
.stt-ok    { color: #059669; }
.stt-error { color: #dc2626; font-weight: 500; }

/* ----- Kết quả ----- */
.stt-result-title { font-size: 19px; font-weight: 700; color: var(--stt-ink); }

/* ----- Khung chat ----- */
.stt-chat-wrap {
  border: 1px solid var(--stt-border); border-radius: 16px;
  background: #fbfbfd; overflow: hidden;
}
.stt-chat {
  max-height: 560px; overflow-y: auto;
  padding: 20px; display: flex; flex-direction: column; gap: 14px;
}
.stt-row { display: flex; width: 100%; }
.stt-customer { justify-content: flex-start; }
.stt-agent    { justify-content: flex-end; }

.stt-bubble {
  max-width: 78%; padding: 10px 14px; border-radius: 16px;
  font-size: 14.5px; line-height: 1.55;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .06);
}
.stt-customer .stt-bubble {
  background: var(--stt-customer); color: var(--stt-ink);
  border: 1px solid var(--stt-border); border-bottom-left-radius: 5px;
}
.stt-agent .stt-bubble {
  background: linear-gradient(135deg, var(--stt-agent-from), var(--stt-agent-to));
  color: #fff; border-bottom-right-radius: 5px;
}

.stt-meta {
  display: flex; align-items: baseline; gap: 8px;
  font-size: 11px; margin-bottom: 4px;
}
.stt-name { font-weight: 700; letter-spacing: .04em; }
.stt-customer .stt-name { color: var(--stt-agent-from); }
.stt-agent    .stt-name { color: rgba(255, 255, 255, .92); }
.stt-time { font-variant-numeric: tabular-nums; }
.stt-customer .stt-time { color: var(--stt-muted); }
.stt-agent    .stt-time { color: rgba(255, 255, 255, .72); }
.stt-text { white-space: pre-wrap; word-break: break-word; }

/* ----- Legend ----- */
.stt-legend {
  display: flex; justify-content: center; gap: 24px;
  padding: 12px; border-top: 1px solid var(--stt-border);
  background: #fff; font-size: 13px; color: var(--stt-muted);
}
.stt-legend-item { display: inline-flex; align-items: center; gap: 7px; }
.stt-dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.stt-dot-agent {
  background: linear-gradient(135deg, var(--stt-agent-from), var(--stt-agent-to));
}
.stt-dot-customer { background: #fff; border: 2px solid #cbd0d8; }

/* ----- Điện thoại ----- */
@media (max-width: 640px) {
  .stt-header h1 { font-size: 24px; }
  .stt-bubble { max-width: 90%; }
  .stt-chat { padding: 14px; max-height: 62vh; }
  .stt-legend { gap: 14px; font-size: 12px; }
}

/* ----- Dark mode ----- */
.dark .stt-card, .dark .stt-legend { background: #1f2937; }
.dark .stt-chat-wrap { background: #111827; border-color: #374151; }
.dark .stt-legend { border-color: #374151; }
.dark .stt-customer .stt-bubble { background: #374151; color: #f3f4f6; border-color: #4b5563; }
.dark .stt-result-title { color: #f3f4f6; }
.dark .stt-customer .stt-name { color: #a5b4fc; }
"""

# Gradio hiển thị vùng kéo-thả bằng tiếng Anh; dịch sang tiếng Việt ở phía client.
LOCALIZE_JS = """
() => {
  const DICT = {
    "Drop File Here": "Kéo thả file vào đây",
    "Click to Upload": "Bấm để chọn file",
    "or": "hoặc",
  };
  // Các chuỗi này nằm ở text node trực tiếp, không bọc trong thẻ riêng.
  const localize = () => {
    const root = document.querySelector('.gradio-container');
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const key = node.textContent.trim();
      if (DICT[key] && node.textContent !== DICT[key]) node.textContent = DICT[key];
    }
  };
  localize();
  new MutationObserver(localize).observe(document.body, {childList: true, subtree: true});
}
"""

COPY_JS = """
() => {
  const box = document.querySelector('#stt_raw textarea');
  if (!box || !box.value) return;
  navigator.clipboard.writeText(box.value).catch(() => {});
}
"""

with gr.Blocks(
    css=CSS,
    title="Chuyển đổi Giọng nói",
    theme=gr.themes.Soft(),
    analytics_enabled=False,
    delete_cache=(1800, 1800),  # dọn file tạm mỗi 30 phút
) as demo:
    gr.HTML(
        '<div class="stt-header">'
        "<h1>Chuyển đổi Giọng nói</h1>"
        "<p>Công cụ AI chuyển đổi âm thanh thành văn bản tiếng Việt chính xác</p>"
        "</div>"
    )

    # ---------------- Màn hình 1: Upload ----------------
    with gr.Column(visible=True) as upload_screen:
        with gr.Group(elem_classes="stt-card"):
            audio_input = gr.File(
                label="Tải lên file ghi âm cuộc gọi",
                file_types=ACCEPTED_EXTS,
                file_count="single",
                type="filepath",
            )
        gr.HTML(
            '<div class="stt-hint">Hỗ trợ .mp3, .wav, .m4a — tối đa '
            f"{MAX_FILE_MB}MB. File 15 phút xử lý dưới 15 giây.</div>"
        )

        with gr.Accordion("Tuỳ chọn nâng cao", open=False):
            engine_input = gr.Radio(
                choices=ENGINE_CHOICES or [("Chưa cấu hình API key", "deepgram")],
                value=DEFAULT_ENGINE,
                label="Engine nhận dạng",
                interactive=bool(ENGINE_CHOICES),
            )
            language_input = gr.Dropdown(
                choices=["vi", "en", "multi"], value="vi", label="Ngôn ngữ"
            )
            swap_input = gr.Checkbox(
                value=False,
                label="Đảo vai hai người nói (dùng khi thẩm định viên bị nhận nhầm thành khách hàng)",
            )

        analyze_button = gr.Button("Phân tích cuộc gọi", variant="primary", size="lg")

    status_output = gr.HTML("")

    # ---------------- Màn hình 2: Kết quả ----------------
    with gr.Column(visible=False) as result_screen:
        with gr.Row(equal_height=True):
            result_header = gr.HTML("")
            copy_button = gr.Button("Sao chép nội dung", size="sm", scale=0)

        chat_output = gr.HTML("")
        # Giữ trong DOM (không dùng visible=False, vì Gradio sẽ không render)
        # để nút "Sao chép nội dung" đọc được nội dung từ đây.
        raw_output = gr.Textbox(
            elem_id="stt_raw", elem_classes="stt-hidden", show_label=False, container=False
        )

        back_button = gr.Button("← Phân tích cuộc gọi khác", size="lg")

    # ---------------- Sự kiện ----------------
    analyze_button.click(
        fn=analyze,
        inputs=[audio_input, engine_input, language_input, swap_input],
        outputs=[
            chat_output,
            result_header,
            raw_output,
            status_output,
            upload_screen,
            result_screen,
        ],
        concurrency_limit=CONCURRENCY_LIMIT,
        show_progress="minimal",
    )

    copy_button.click(fn=None, inputs=None, outputs=None, js=COPY_JS)

    back_button.click(
        fn=reset,
        inputs=None,
        outputs=[
            audio_input,
            chat_output,
            result_header,
            raw_output,
            status_output,
            upload_screen,
            result_screen,
        ],
    )

    demo.load(fn=None, inputs=None, outputs=None, js=LOCALIZE_JS)


demo.queue(default_concurrency_limit=CONCURRENCY_LIMIT, max_size=QUEUE_MAX_SIZE)


def _auth():
    """Bật đăng nhập nếu đặt APP_USERNAME + APP_PASSWORD (Space công khai nên bật)."""
    user = os.getenv("APP_USERNAME", "").strip()
    password = os.getenv("APP_PASSWORD", "").strip()
    if user and password:
        log.info("Đã bật đăng nhập cho tài khoản '%s'", user)
        return (user, password)
    if IS_SPACE:
        log.warning(
            "Space đang chạy KHÔNG có đăng nhập — bất kỳ ai cũng dùng được API key của bạn. "
            "Đặt APP_USERNAME và APP_PASSWORD để giới hạn truy cập."
        )
    return None


if __name__ == "__main__":
    demo.launch(
        server_name=os.getenv("HOST", "0.0.0.0"),
        server_port=_env_int("PORT", 7860),
        max_file_size=f"{MAX_FILE_MB}mb",
        auth=_auth(),
        ssr_mode=False,
        show_api=False,
        show_error=False,
    )
