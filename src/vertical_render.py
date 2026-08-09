"""Xuất video dọc 9:16 (1080x1920) chất lượng cao cho TikTok / Reels / Shorts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .intro_maker import probe_video
from .progress import ProgressReporter
from .utils import PipelineError, run_ffmpeg

TIKTOK_WIDTH = 1080
TIKTOK_HEIGHT = 1920

# Chế độ lấp phần trống khi video gốc không phải 9:16.
FILL_MODES = {
    "blur": "Nền mờ từ chính video (khuyên dùng)",
    "black": "Nền đen",
    "white": "Nền trắng",
    "crop": "Cắt đầy khung (mất hai bên)",
}
DEFAULT_FILL = "blur"

CODECS = {
    "libx264": "H.264 (tương thích mọi nơi)",
    "libx265": "H.265 (file nhẹ hơn, một số nền tảng kén)",
}
DEFAULT_CODEC = "libx264"


@dataclass
class RenderSettings:
    """Thông số xuất bản. Mặc định đã là mức 'nét tối đa' cho mạng xã hội."""

    width: int = TIKTOK_WIDTH
    height: int = TIKTOK_HEIGHT
    fill_mode: str = DEFAULT_FILL
    codec: str = DEFAULT_CODEC
    crf: int = 18
    preset: str = "slow"
    audio_bitrate: str = "192k"
    fps: int = 30
    strip_metadata: bool = True
    blur_radius: int = 40

    def validate(self) -> None:
        if self.fill_mode not in FILL_MODES:
            raise ValueError(f"Chế độ nền không hợp lệ: {self.fill_mode}")
        if self.codec not in CODECS:
            raise ValueError(f"Codec không hợp lệ: {self.codec}")
        if not 0 <= self.crf <= 51:
            raise ValueError("CRF phải nằm trong khoảng 0-51 (18 là mức nét cao).")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Kích thước khung hình phải lớn hơn 0.")

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def build_video_filter(settings: RenderSettings) -> str:
    """Filter graph đưa mọi tỉ lệ video về đúng khung dọc mà không méo hình."""
    width, height = settings.width, settings.height
    fit = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos"
    )

    if settings.fill_mode == "crop":
        # Phóng to cho phủ kín rồi cắt - không có viền nhưng mất rìa hai bên.
        return (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},setsar=1,fps={settings.fps}[vout]"
        )

    if settings.fill_mode in ("black", "white"):
        colour = "black" if settings.fill_mode == "black" else "white"
        return (
            f"[0:v]{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:{colour},"
            f"setsar=1,fps={settings.fps}[vout]"
        )

    # blur: nền là chính video được phóng to, cắt kín khung rồi làm mờ.
    return (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},"
        f"boxblur=luma_radius={settings.blur_radius}:luma_power=1:"
        f"chroma_radius={max(1, settings.blur_radius // 2)}:chroma_power=1,"
        "eq=brightness=-0.06[bgb];"
        f"[fg]{fit}[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={settings.fps}[vout]"
    )


def build_ffmpeg_args(
    video: Path,
    output: Path,
    settings: RenderSettings,
    audio: Optional[Path] = None,
) -> List[str]:
    """Danh sách tham số ffmpeg đầy đủ (tách riêng để test được không cần render)."""
    settings.validate()

    args: List[str] = ["-i", str(video)]
    if audio is not None:
        args += ["-i", str(audio)]

    args += ["-filter_complex", build_video_filter(settings), "-map", "[vout]"]
    args += ["-map", "1:a:0"] if audio is not None else ["-map", "0:a:0?"]

    args += [
        "-c:v", settings.codec,
        "-crf", str(settings.crf),
        "-preset", settings.preset,
        "-pix_fmt", "yuv420p",
        "-profile:v", "high" if settings.codec == "libx264" else "main",
        "-c:a", "aac",
        "-b:a", settings.audio_bitrate,
        "-ar", "48000",
        # faststart để nền tảng bắt đầu phát ngay khi chưa tải xong file.
        "-movflags", "+faststart",
    ]
    if settings.strip_metadata:
        args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    if audio is not None:
        args.append("-shortest")

    args.append(str(output))
    return args


class VerticalRenderer:
    """Render bản cuối theo khung dọc, dùng chung cho Bot và pipeline thường."""

    def __init__(self, settings: Optional[RenderSettings] = None) -> None:
        self.settings = settings or RenderSettings()

    def describe(self, video: Path) -> str:
        """Câu mô tả việc sắp làm, để ghi vào log cho người dùng thấy."""
        info = probe_video(Path(video))
        source = f"{info.width}x{info.height}"
        if info.width == self.settings.width and info.height == self.settings.height:
            return f"Video đã đúng khung {self.settings.resolution}, chỉ mã hoá lại."
        if info.is_vertical:
            return f"Đưa {source} về {self.settings.resolution} (dọc sẵn, chỉ scale)."
        return (
            f"Video ngang {source} → {self.settings.resolution}, "
            f"lấp nền bằng: {FILL_MODES[self.settings.fill_mode]}"
        )

    def render(
        self,
        video: Path,
        output: Path,
        reporter: ProgressReporter,
        audio: Optional[Path] = None,
    ) -> Path:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        reporter.log(self.describe(video))
        reporter.log(
            f"Mã hoá {self.settings.codec} CRF={self.settings.crf} "
            f"preset={self.settings.preset}, audio {self.settings.audio_bitrate}"
            f"{' · xoá metadata cũ' if self.settings.strip_metadata else ''}"
        )
        if self.settings.preset in ("slow", "slower", "veryslow"):
            reporter.log("⏳ Preset chậm cho chất lượng cao nhất - bước này sẽ lâu.")

        try:
            run_ffmpeg(build_ffmpeg_args(Path(video), output, self.settings, audio))
        except PipelineError:
            if self.settings.codec == "libx265":
                reporter.log("⚠ libx265 lỗi - thử lại bằng libx264.")
                fallback = RenderSettings(**{**self.settings.__dict__, "codec": "libx264"})
                run_ffmpeg(build_ffmpeg_args(Path(video), output, fallback, audio))
            else:
                raise

        reporter.progress(1.0)
        return output
