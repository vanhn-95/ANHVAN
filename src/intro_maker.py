"""Tạo intro 3 giây (nền + chữ zoom) và ghép vào đầu video."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .progress import ProgressReporter
from .utils import PipelineError, ffprobe_path, run_ffmpeg

INTRO_SECONDS = 3.0
FALLBACK_TEXT = "XEM NGAY"

# Font phải có dấu tiếng Việt. Tìm theo thứ tự ưu tiên trên từng hệ điều hành.
FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]

# Nền gradient đẹp, hợp TikTok. (màu trên, màu dưới)
BACKGROUNDS = {
    "tim": ("0x2b1055", "0x7597de"),
    "cam": ("0xff512f", "0xdd2476"),
    "xanh": ("0x0f2027", "0x2c5364"),
    "toi": ("0x141e30", "0x243b55"),
}
DEFAULT_BACKGROUND = "tim"


@dataclass
class VideoInfo:
    width: int = 1080
    height: int = 1920
    fps: float = 30.0

    @property
    def is_vertical(self) -> bool:
        return self.height >= self.width


def find_font() -> Optional[str]:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def probe_video(path: Path) -> VideoInfo:
    """Đọc kích thước + fps để intro khớp với video chính."""
    exe = ffprobe_path()
    if not exe:
        return VideoInfo()

    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 3:
        return VideoInfo()

    try:
        width, height = int(lines[0]), int(lines[1])
        numerator, _, denominator = lines[2].partition("/")
        fps = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return VideoInfo()

    return VideoInfo(width=width, height=height, fps=min(max(fps, 1.0), 60.0))


def escape_drawtext(text: str) -> str:
    """Thoát ký tự cho filter drawtext.

    drawtext parse chuỗi hai lớp: dấu ``\\``, ``:``, ``'`` và ``%`` đều phải thoát,
    nếu không filter graph sẽ gãy hoặc bị hiểu nhầm thành tham số khác.
    """
    out = text.replace("\\", r"\\\\")
    out = out.replace("'", r"\'")
    out = out.replace(":", r"\:")
    out = out.replace("%", r"\%")
    return out


def wrap_text(text: str, max_chars: int = 16) -> List[str]:
    """Ngắt dòng theo từ để chữ to không tràn khung."""
    words = text.split()
    if not words:
        return [FALLBACK_TEXT]

    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


class IntroMaker:
    """Dựng clip intro 3 giây rồi nối vào đầu video chính."""

    def __init__(self, workspace: Path, background: str = DEFAULT_BACKGROUND) -> None:
        self.workspace = Path(workspace)
        self.background = background if background in BACKGROUNDS else DEFAULT_BACKGROUND
        self.workspace.mkdir(parents=True, exist_ok=True)

    def build_filter(self, text: str, info: VideoInfo) -> str:
        """Filter graph: gradient → chữ nhiều dòng → zoom dần."""
        font = find_font()
        if not font:
            raise PipelineError(
                "Không tìm thấy font nào để vẽ chữ intro. "
                "Cài font (Linux: apt install fonts-dejavu) rồi thử lại."
            )

        top, bottom = BACKGROUNDS[self.background]
        lines = wrap_text(text)
        # Bề rộng trung bình một ký tự chữ đậm ≈ 0.58 × cỡ chữ. Chỉ dùng 72% bề
        # ngang khung vì zoompan sẽ phóng to và cắt bớt mép hai bên.
        longest = max(len(line) for line in lines)
        font_size = int(info.width * 0.72 / (0.58 * max(longest, 4)))
        font_size = max(28, min(font_size, info.width // 5))
        line_height = int(font_size * 1.25)
        start_y = f"(h-{len(lines) * line_height})/2"

        # gradients: dùng hai nguồn màu chồng lên nhau qua vertical fade.
        parts = [
            f"color=c={top}:s={info.width}x{info.height}:d={INTRO_SECONDS}:r={info.fps:.0f}[top]",
            f"color=c={bottom}:s={info.width}x{info.height}:d={INTRO_SECONDS}:r={info.fps:.0f}[bot]",
            f"[top][bot]blend=all_expr='A*(1-Y/H)+B*(Y/H)'[bg]",
        ]

        stream = "bg"
        for index, line in enumerate(lines):
            y = f"{start_y}+{index * line_height}"
            parts.append(
                f"[{stream}]drawtext=fontfile='{font}':text='{escape_drawtext(line)}'"
                f":fontcolor=white:fontsize={font_size}"
                f":borderw={max(2, font_size // 14)}:bordercolor=black@0.55"
                f":x=(w-text_w)/2:y={y}[t{index}]"
            )
            stream = f"t{index}"

        # Zoom nhẹ 1.0 → 1.12 trong 3 giây cho cảm giác chuyển động.
        total_frames = int(INTRO_SECONDS * info.fps)
        zoom_step = 0.12 / max(1, total_frames)
        parts.append(
            f"[{stream}]zoompan=z='min(zoom+{zoom_step:.5f},1.12)':d={total_frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={info.width}x{info.height}:fps={info.fps:.0f}[zoomed]"
        )
        parts.append(f"[zoomed]fade=t=out:st={INTRO_SECONDS - 0.4:.2f}:d=0.4[vout]")
        # Audio im lặng dựng luôn trong graph để intro có sẵn track tiếng khi concat.
        parts.append(f"anullsrc=r=44100:cl=stereo:d={INTRO_SECONDS}[aout]")
        return ";".join(parts)

    def build(self, text: str, like_video: Path, reporter: ProgressReporter) -> Path:
        """Render intro.mp4 cùng kích thước/fps với video chính."""
        text = (text or "").strip() or FALLBACK_TEXT
        info = probe_video(Path(like_video))
        output = self.workspace / "intro.mp4"

        reporter.log(f"Tạo intro {INTRO_SECONDS:.0f}s: “{text}” ({info.width}x{info.height})")
        run_ffmpeg([
            "-filter_complex", self.build_filter(text, info),
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{INTRO_SECONDS}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            str(output),
        ])
        return output

    def prepend(self, intro: Path, video: Path, output: Path,
                reporter: ProgressReporter) -> Path:
        """Nối intro + video chính. Chuẩn hoá về cùng kích thước rồi concat."""
        info = probe_video(Path(video))
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        reporter.log("Ghép intro vào đầu video...")
        scale = (
            f"scale={info.width}:{info.height}:force_original_aspect_ratio=decrease,"
            f"pad={info.width}:{info.height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,fps={info.fps:.0f}"
        )
        filter_complex = (
            f"[0:v]{scale}[v0];[1:v]{scale}[v1];"
            "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a0];"
            "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a1];"
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]"
        )
        run_ffmpeg([
            "-i", str(intro), "-i", str(video),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ])
        return output


def default_intro_from_segments(segments: Sequence, limit: int = 24) -> str:
    """Intro dự phòng khi không gọi được AI: lấy câu đầu, cắt ngắn, viết hoa."""
    for segment in segments:
        text = (getattr(segment, "translated", "") or getattr(segment, "text", "")).strip()
        if text:
            words = text.split()
            short = ""
            for word in words:
                if len(f"{short} {word}".strip()) > limit:
                    break
                short = f"{short} {word}".strip()
            return (short or text[:limit]).upper().rstrip(".,!?")
    return FALLBACK_TEXT
