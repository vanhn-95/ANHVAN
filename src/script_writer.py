"""Viết lại kịch bản theo phong cách TikTok và phân tích cảm xúc video.

Dùng chung factory ``TranslatorAgent`` nên chạy được với Gemini / OpenAI / DeepSeek.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .progress import ProgressReporter
from .providers import ProviderError, TranslatorAgent, parse_numbered
from .utils import Segment

BATCH_SIZE = 30

# Prompt cốt lõi. Giữ nguyên văn theo yêu cầu, chỉ thêm phần ràng buộc định dạng
# đánh số ở cuối để số dòng ra luôn khớp số dòng vào (không lệch mốc thời gian).
TIKTOK_SCRIPT_PROMPT = """Hãy đóng vai một Content Creator TikTok chuyên nghiệp. \
Viết lại lời dẫn (script) sau theo phong cách TikTok Việt Nam. Yêu cầu: Giọng điệu tự \
nhiên, gần gũi, có cảm xúc cao (hào hứng, ngạc nhiên, thân mật), sử dụng từ ngữ trending \
của Gen Z. Ngắn gọn súc tích nhưng vẫn đầy đủ thông điệp. Mục tiêu thu hút người xem dừng \
lại giây đầu tiên. Không dịch máy, hãy diễn đạt lại theo văn phong người Việt Nam đang nói \
chuyện trên mạng xã hội. Sử dụng dấu hỏi (?), dấu chấm than (!) và câu hỏi tu từ để giọng \
TTS khi đọc lên sẽ có nhịp điệu và cảm xúc.

RÀNG BUỘC ĐỊNH DẠNG (bắt buộc tuân thủ tuyệt đối):
- Mỗi dòng đầu vào là một câu thoại có mốc thời gian riêng.
- Trả về ĐÚNG {count} dòng, mỗi dòng bắt đầu bằng số thứ tự và dấu gạch đứng: `1|nội dung`
- KHÔNG gộp dòng, KHÔNG tách dòng, KHÔNG đổi thứ tự, KHÔNG bỏ dòng nào.
- Mỗi dòng viết lại phải dài xấp xỉ dòng gốc để khớp thời lượng khi lồng tiếng.
- Mỗi dòng phải có dấu câu đầy đủ ở cuối (. ? !).
- Không thêm lời bình, không markdown, không dòng trống.

Các dòng cần viết lại:
{payload}"""

MOOD_PROMPT = """Đọc kịch bản video dưới đây và phân tích tâm trạng chủ đạo.

Chỉ trả về JSON thuần, không markdown, đúng dạng:
{{"mood": "<một trong: Nhẹ nhàng, Sôi động, Hài hước, Buồn, Gây cấn>", \
"genres": ["<thể loại nhạc 1>", "<thể loại nhạc 2>", "<thể loại nhạc 3>"], \
"reason": "<một câu tiếng Việt giải thích>"}}

Kịch bản:
{script}"""

INTRO_PROMPT = """Bạn là chuyên gia viết tiêu đề TikTok câu view.

Đọc nội dung video dưới đây rồi viết MỘT câu intro cực ngắn để hiện 3 giây đầu video.

Yêu cầu:
- Tối đa 5 từ, viết IN HOA toàn bộ.
- Gây tò mò hoặc gây sốc nhẹ, đúng nội dung video, không bịa.
- Không dấu ngoặc kép, không emoji, không giải thích gì thêm.
- Chỉ trả về đúng câu intro, không gì khác.

Nội dung video:
{script}"""

MOODS = ["Nhẹ nhàng", "Sôi động", "Hài hước", "Buồn", "Gây cấn"]
DEFAULT_MOOD = "Nhẹ nhàng"

# Gợi ý nhạc dự phòng khi không gọi được AI.
FALLBACK_GENRES = {
    "Nhẹ nhàng": ["acoustic", "lofi", "piano"],
    "Sôi động": ["edm", "pop", "upbeat"],
    "Hài hước": ["ukulele", "quirky", "comedy"],
    "Buồn": ["piano", "ambient", "sad"],
    "Gây cấn": ["cinematic", "epic", "tension"],
}


@dataclass
class MoodResult:
    mood: str = DEFAULT_MOOD
    genres: List[str] = None
    reason: str = ""
    from_ai: bool = False

    def __post_init__(self) -> None:
        if not self.genres:
            self.genres = FALLBACK_GENRES.get(self.mood, FALLBACK_GENRES[DEFAULT_MOOD])


class ScriptWriter:
    """Viết lại lời thoại, đoán cảm xúc, và nghĩ câu intro."""

    def __init__(self, provider: str, api_key: str, model: str = "") -> None:
        self.agent: TranslatorAgent = TranslatorAgent.create(provider, api_key, model)

    # ----------------------------------------------------------- viết lại script
    def rewrite(
        self,
        segments: Sequence[Segment],
        reporter: ProgressReporter,
    ) -> List[Segment]:
        """Viết lại từng câu theo phong cách TikTok, giữ nguyên số dòng và mốc giờ.

        Viết theo lô và giữ nguyên số dòng vì mỗi câu đã gắn với một mốc thời gian
        trong video; gộp cả kịch bản thành một đoạn văn sẽ làm lệch toàn bộ timeline
        khi lồng tiếng.
        """
        sources = [(segment.translated or segment.text).strip() for segment in segments]
        done = 0

        for start in range(0, len(sources), BATCH_SIZE):
            reporter.check_cancelled()
            batch = sources[start:start + BATCH_SIZE]
            payload = "\n".join(f"{i + 1}|{line}" for i, line in enumerate(batch))
            prompt = TIKTOK_SCRIPT_PROMPT.format(count=len(batch), payload=payload)

            raw = self.agent.complete(prompt)
            rewritten = parse_numbered(raw, len(batch))

            for offset, line in enumerate(rewritten):
                text = ensure_punctuation(line.strip()) if line.strip() else batch[offset]
                segments[start + offset].translated = text

            done += len(batch)
            reporter.progress(done / max(1, len(sources)))
            reporter.log(f"Đã viết lại {done}/{len(sources)} câu theo phong cách TikTok.")

        return list(segments)

    # ------------------------------------------------------------ phân tích mood
    def analyze_mood(self, segments: Sequence[Segment], reporter: ProgressReporter) -> MoodResult:
        script = script_preview(segments)
        if not script:
            return MoodResult()

        try:
            raw = self.agent.complete(MOOD_PROMPT.format(script=script), max_tokens=300)
            data = extract_json(raw)
            mood = str(data.get("mood", DEFAULT_MOOD)).strip()
            if mood not in MOODS:
                mood = DEFAULT_MOOD
            genres = [str(g).strip() for g in data.get("genres", []) if str(g).strip()]
            result = MoodResult(mood=mood, genres=genres,
                                reason=str(data.get("reason", "")), from_ai=True)
        except (ProviderError, ValueError) as exc:
            reporter.log(f"⚠ Không phân tích được cảm xúc bằng AI ({exc}) - dùng mặc định.")
            return MoodResult()

        reporter.log(f"Cảm xúc video: {result.mood} · gợi ý nhạc: {', '.join(result.genres)}")
        return result

    # ------------------------------------------------------------- sinh câu intro
    def suggest_intro(self, segments: Sequence[Segment], reporter: ProgressReporter) -> str:
        script = script_preview(segments)
        if not script:
            return ""
        try:
            raw = self.agent.complete(INTRO_PROMPT.format(script=script), max_tokens=40)
        except ProviderError as exc:
            reporter.log(f"⚠ Không sinh được intro bằng AI ({exc}).")
            return ""

        line = clean_intro(raw)
        if line:
            reporter.log(f"AI đề xuất intro: “{line}”")
        return line


# ------------------------------------------------------------------------ tiện ích
def ensure_punctuation(text: str) -> str:
    """Bảo đảm câu có dấu kết - TTS đọc mới có nhịp và cảm xúc."""
    text = text.strip()
    if not text:
        return text
    if text[-1] in ".!?…":
        return text
    return text + "."


def script_preview(segments: Sequence[Segment], limit: int = 2500) -> str:
    """Nối lời thoại thành đoạn văn để AI đọc, cắt bớt cho khỏi tốn token."""
    parts = []
    total = 0
    for segment in segments:
        text = (segment.translated or segment.text).strip()
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= limit:
            break
    return " ".join(parts)


def extract_json(raw: str) -> dict:
    """Bóc JSON kể cả khi model bọc trong ```json ... ``` hoặc thêm lời dẫn."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Không đọc được JSON từ model: {raw[:150]}") from exc
    if not isinstance(data, dict):
        raise ValueError("Model trả JSON không phải object.")
    return data


def clean_intro(raw: str, max_words: int = 5) -> str:
    """Chuẩn hoá câu intro AI trả về: bỏ ngoặc kép, emoji, cắt còn 5 từ, IN HOA."""
    line = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    line = line.strip().strip('"').strip("'").strip()
    line = re.sub(r"^(intro|tiêu đề|title)\s*[:\-]\s*", "", line, flags=re.IGNORECASE)
    # Giữ chữ, số, khoảng trắng và vài dấu câu; bỏ emoji và ký tự lạ.
    line = re.sub(r"[^\w\s!?.,\-]", "", line, flags=re.UNICODE).strip()
    words = line.split()
    if not words:
        return ""
    return " ".join(words[:max_words]).upper().rstrip(".,")


def resolve_intro_text(
    manual: str,
    auto_enabled: bool,
    writer: Optional[ScriptWriter],
    segments: Sequence[Segment],
    reporter: ProgressReporter,
) -> str:
    """Quyết định chữ intro: người dùng nhập > AI sinh > lấy từ câu đầu."""
    manual = (manual or "").strip()
    if manual:
        return manual

    if auto_enabled and writer is not None:
        suggested = writer.suggest_intro(segments, reporter)
        if suggested:
            return suggested

    from .intro_maker import default_intro_from_segments

    fallback = default_intro_from_segments(segments)
    reporter.log(f"Dùng intro dự phòng từ câu đầu: “{fallback}”")
    return fallback
