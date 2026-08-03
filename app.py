"""
Chuyển đổi Giọng nói — Speech-to-Text phân tích cuộc gọi.

Ứng dụng web hiển thị bản ghi cuộc gọi dưới dạng khung chat đối thoại,
tự động tách 2 người nói (speaker diarization).

Chạy:  python app.py
"""

from __future__ import annotations

import html
import os
import time
from dataclasses import dataclass

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------- #
# Cấu hình
# --------------------------------------------------------------------------- #

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")
GROQ_MODEL = os.getenv("GROQ_MODEL", "whisper-large-v3-turbo")

# Timeout đủ rộng cho file dài, nhưng vẫn fail nhanh nếu mạng chết.
REQUEST_TIMEOUT = (10, 180)  # (connect, read)

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


class TranscriptionError(Exception):
    """Lỗi có thông điệp thân thiện để hiển thị thẳng cho người dùng."""


# --------------------------------------------------------------------------- #
# STT engines
# --------------------------------------------------------------------------- #


def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def transcribe_deepgram(path: str, language: str) -> list[Turn]:
    """Deepgram Nova-2: diarization gốc, trả về utterances đã tách người nói."""
    params = {
        "model": DEEPGRAM_MODEL,
        "language": language,
        "diarize": "true",
        "punctuate": "true",
        "smart_format": "true",
        "utterances": "true",
        "filler_words": "false",
    }
    with open(path, "rb") as fh:
        response = requests.post(
            DEEPGRAM_URL,
            params=params,
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": _guess_mime(path),
            },
            data=fh,
            timeout=REQUEST_TIMEOUT,
        )

    if response.status_code == 401:
        raise TranscriptionError("DEEPGRAM_API_KEY không hợp lệ. Kiểm tra lại file .env.")
    if not response.ok:
        raise TranscriptionError(f"Deepgram trả về lỗi {response.status_code}: {response.text[:300]}")

    payload = response.json()
    utterances = payload.get("results", {}).get("utterances") or []

    if not utterances:
        # Không có utterances (hiếm) — lấy transcript phẳng làm 1 lượt thoại.
        channels = payload.get("results", {}).get("channels") or []
        alternatives = channels[0].get("alternatives") if channels else None
        flat = (alternatives[0].get("transcript") if alternatives else "") or ""
        return [Turn(speaker=0, start=0.0, text=flat)] if flat.strip() else []

    segments = [
        Turn(
            speaker=int(item.get("speaker", 0) or 0),
            start=float(item.get("start", 0.0) or 0.0),
            text=(item.get("transcript") or "").strip(),
        )
        for item in utterances
    ]
    return [seg for seg in segments if seg.text]


def transcribe_groq(path: str, language: str) -> list[Turn]:
    """Groq Whisper: rất nhanh nhưng KHÔNG có diarization gốc.

    Người nói được suy đoán bằng khoảng lặng giữa các segment — chỉ mang tính
    tương đối. Dùng Deepgram nếu cần độ chính xác tách vai.
    """
    with open(path, "rb") as fh:
        response = requests.post(
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

    if response.status_code == 401:
        raise TranscriptionError("GROQ_API_KEY không hợp lệ. Kiểm tra lại file .env.")
    if response.status_code == 413:
        raise TranscriptionError(
            "File vượt quá giới hạn dung lượng của Groq (~25MB). "
            "Hãy nén file hoặc dùng Deepgram."
        )
    if not response.ok:
        raise TranscriptionError(f"Groq trả về lỗi {response.status_code}: {response.text[:300]}")

    payload = response.json()
    segments = payload.get("segments") or []

    if not segments:
        flat = (payload.get("text") or "").strip()
        return [Turn(speaker=0, start=0.0, text=flat)] if flat else []

    # Heuristic: khoảng lặng dài giữa 2 segment => nhiều khả năng đổi người nói.
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
        turns.append(Turn(speaker=speaker, start=start, text=text))
        previous_end = float(segment.get("end", start) or start)

    return turns


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
    """Theo mặc định: Speaker 0 = khách hàng (trái), Speaker 1 = thẩm định viên (phải)."""
    is_agent = speaker != 0
    if swap:
        is_agent = not is_agent
    return "agent" if is_agent else "customer"


def render_chat(turns: list[Turn], swap: bool) -> str:
    """Dựng khung chat timeline + legend."""
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
    lines = []
    for turn in turns:
        label = LABEL_AGENT if role_of(turn.speaker, swap) == "agent" else LABEL_CUSTOMER
        lines.append(f"[{format_timestamp(turn.start)}] {label}: {turn.text}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Handler chính
# --------------------------------------------------------------------------- #


def analyze(file_path: str | None, engine: str, language: str, swap: bool):
    """Trả về: chat_html, header_html, raw_text, status, upload_screen, result_screen."""
    keep_upload = gr.update(visible=True)
    keep_result = gr.update(visible=False)

    def fail(message: str):
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            f'<div class="stt-status stt-error">{html.escape(message)}</div>',
            keep_upload,
            keep_result,
        )

    if not file_path:
        return fail("Vui lòng chọn một file ghi âm trước khi phân tích.")

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ACCEPTED_EXTS:
        return fail(f"Định dạng {ext or 'không xác định'} chưa được hỗ trợ. Hãy dùng .mp3, .wav hoặc .m4a.")

    use_deepgram = engine.startswith("Deepgram")
    if use_deepgram and not DEEPGRAM_API_KEY:
        return fail("Chưa có DEEPGRAM_API_KEY. Thêm key vào file .env rồi khởi động lại ứng dụng.")
    if not use_deepgram and not GROQ_API_KEY:
        return fail("Chưa có GROQ_API_KEY. Thêm key vào file .env rồi khởi động lại ứng dụng.")

    started = time.perf_counter()
    try:
        raw_segments = (
            transcribe_deepgram(file_path, language)
            if use_deepgram
            else transcribe_groq(file_path, language)
        )
    except TranscriptionError as exc:
        return fail(str(exc))
    except requests.exceptions.Timeout:
        return fail("Hết thời gian chờ phản hồi từ API. Kiểm tra kết nối mạng và thử lại.")
    except requests.exceptions.RequestException as exc:
        return fail(f"Không kết nối được tới API: {exc}")

    elapsed = time.perf_counter() - started

    turns = merge_turns(raw_segments)
    if not turns:
        return fail("Không nhận được nội dung nào từ file này. File có thể bị lỗi hoặc không có tiếng nói.")

    engine_name = f"Deepgram {DEEPGRAM_MODEL}" if use_deepgram else f"Groq {GROQ_MODEL}"
    status = (
        f'<div class="stt-status stt-ok">Hoàn tất trong <b>{elapsed:.1f}s</b> · {engine_name}</div>'
    )

    return (
        render_chat(turns, swap),
        render_result_header(len(turns)),
        to_plain_text(turns, swap),
        status,
        gr.update(visible=False),
        gr.update(visible=True),
    )


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
  navigator.clipboard.writeText(box.value).catch(() => {
    box.select();
    document.execCommand('copy');
  });
}
"""

with gr.Blocks(css=CSS, title="Chuyển đổi Giọng nói", theme=gr.themes.Soft()) as demo:
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
        gr.HTML('<div class="stt-hint">Hỗ trợ .mp3, .wav, .m4a — file 15 phút xử lý dưới 15 giây.</div>')

        with gr.Accordion("Tuỳ chọn nâng cao", open=False):
            engine_input = gr.Radio(
                choices=[
                    "Deepgram Nova-2 (khuyến nghị — tách người nói chính xác)",
                    "Groq Whisper (nhanh nhất — tách người nói tương đối)",
                ],
                value="Deepgram Nova-2 (khuyến nghị — tách người nói chính xác)",
                label="Engine nhận dạng",
            )
            language_input = gr.Dropdown(
                choices=["vi", "en", "multi"],
                value="vi",
                label="Ngôn ngữ",
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
            elem_id="stt_raw",
            elem_classes="stt-hidden",
            show_label=False,
            container=False,
        )

        back_button = gr.Button("← Phân tích cuộc gọi khác", size="lg")

    # ---------------- Sự kiện ----------------
    analyze_button.click(
        fn=analyze,
        inputs=[audio_input, engine_input, language_input, swap_input],
        outputs=[chat_output, result_header, raw_output, status_output, upload_screen, result_screen],
        show_progress="minimal",
    )

    copy_button.click(fn=None, inputs=None, outputs=None, js=COPY_JS)

    demo.load(fn=None, inputs=None, outputs=None, js=LOCALIZE_JS)

    back_button.click(
        fn=reset,
        inputs=None,
        outputs=[audio_input, chat_output, result_header, raw_output, status_output, upload_screen, result_screen],
    )


if __name__ == "__main__":
    demo.launch(
        server_name=os.getenv("HOST", "0.0.0.0"),
        server_port=int(os.getenv("PORT", "7860")),
        show_api=False,
    )
