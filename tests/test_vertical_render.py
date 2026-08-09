"""Test xuất video dọc 9:16 chất lượng cao."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.intro_maker import probe_video
from src.progress import ProgressReporter
from src.vertical_render import (
    CODECS,
    FILL_MODES,
    TIKTOK_HEIGHT,
    TIKTOK_WIDTH,
    RenderSettings,
    VerticalRenderer,
    build_ffmpeg_args,
    build_video_filter,
)

has_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="Cần FFmpeg")


@pytest.fixture
def reporter():
    return ProgressReporter(on_log=lambda _: None)


def make_video(path: Path, width: int, height: int, seconds: float = 2.0) -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path),
    ], check=True)
    return path


class TestDefaults:
    def test_tiktok_defaults(self):
        settings = RenderSettings()
        assert (settings.width, settings.height) == (TIKTOK_WIDTH, TIKTOK_HEIGHT)
        assert settings.crf == 18
        assert settings.preset == "slow"
        assert settings.audio_bitrate == "192k"
        assert settings.strip_metadata is True

    def test_resolution_string(self):
        assert RenderSettings().resolution == "1080x1920"


class TestValidation:
    def test_rejects_bad_fill_mode(self):
        with pytest.raises(ValueError, match="nền"):
            RenderSettings(fill_mode="cau-vong").validate()

    def test_rejects_bad_codec(self):
        with pytest.raises(ValueError, match="Codec"):
            RenderSettings(codec="av1").validate()

    def test_rejects_crf_out_of_range(self):
        with pytest.raises(ValueError, match="CRF"):
            RenderSettings(crf=99).validate()

    def test_rejects_zero_size(self):
        with pytest.raises(ValueError, match="Kích thước"):
            RenderSettings(width=0).validate()

    def test_all_declared_modes_valid(self):
        for mode in FILL_MODES:
            RenderSettings(fill_mode=mode).validate()
        for codec in CODECS:
            RenderSettings(codec=codec).validate()


class TestVideoFilter:
    def test_blur_mode_has_two_layers(self):
        graph = build_video_filter(RenderSettings(fill_mode="blur"))
        assert "split=2" in graph
        assert "boxblur" in graph
        assert "overlay" in graph
        assert "force_original_aspect_ratio=decrease" in graph

    def test_black_mode_uses_pad(self):
        graph = build_video_filter(RenderSettings(fill_mode="black"))
        assert "pad=1080:1920" in graph
        assert "boxblur" not in graph

    def test_crop_mode_fills_frame(self):
        graph = build_video_filter(RenderSettings(fill_mode="crop"))
        assert "crop=1080:1920" in graph
        assert "force_original_aspect_ratio=increase" in graph

    def test_every_mode_emits_vout(self):
        for mode in FILL_MODES:
            assert "[vout]" in build_video_filter(RenderSettings(fill_mode=mode))

    def test_custom_resolution_flows_through(self):
        graph = build_video_filter(RenderSettings(width=720, height=1280))
        assert "720:1280" in graph


class TestFfmpegArgs:
    def _args(self, **kwargs) -> list:
        return build_ffmpeg_args(Path("in.mp4"), Path("out.mp4"), RenderSettings(**kwargs))

    def test_quality_flags_present(self):
        args = self._args()
        assert "-crf" in args and args[args.index("-crf") + 1] == "18"
        assert "-preset" in args and args[args.index("-preset") + 1] == "slow"
        assert "-b:a" in args and args[args.index("-b:a") + 1] == "192k"
        assert "libx264" in args

    def test_metadata_stripped_by_default(self):
        args = self._args()
        assert "-map_metadata" in args
        assert args[args.index("-map_metadata") + 1] == "-1"

    def test_metadata_kept_when_disabled(self):
        assert "-map_metadata" not in self._args(strip_metadata=False)

    def test_faststart_for_streaming(self):
        assert "+faststart" in self._args()

    def test_yuv420p_for_compatibility(self):
        args = self._args()
        assert args[args.index("-pix_fmt") + 1] == "yuv420p"

    def test_external_audio_is_mapped(self):
        args = build_ffmpeg_args(
            Path("in.mp4"), Path("out.mp4"), RenderSettings(), audio=Path("voice.wav")
        )
        assert "1:a:0" in args
        assert "-shortest" in args

    def test_without_audio_uses_source_track(self):
        assert "0:a:0?" in self._args()

    def test_x265_switches_profile(self):
        assert "libx265" in self._args(codec="libx265")


class TestDescribe:
    @has_ffmpeg
    def test_landscape_mentions_background(self, tmp_path):
        video = make_video(tmp_path / "wide.mp4", 1280, 720)
        text = VerticalRenderer().describe(video)
        assert "ngang" in text
        assert "nền" in text.lower()

    @has_ffmpeg
    def test_already_vertical_is_noted(self, tmp_path):
        video = make_video(tmp_path / "tall.mp4", 1080, 1920)
        assert "đúng khung" in VerticalRenderer().describe(video)


@has_ffmpeg
class TestRender:
    def test_landscape_becomes_1080x1920(self, tmp_path, reporter):
        video = make_video(tmp_path / "wide.mp4", 1280, 720)
        out = VerticalRenderer(RenderSettings(preset="veryfast")).render(
            video, tmp_path / "out.mp4", reporter
        )
        info = probe_video(out)
        assert (info.width, info.height) == (1080, 1920)

    def test_square_becomes_vertical(self, tmp_path, reporter):
        video = make_video(tmp_path / "sq.mp4", 720, 720)
        out = VerticalRenderer(RenderSettings(preset="veryfast")).render(
            video, tmp_path / "out.mp4", reporter
        )
        assert probe_video(out).height == 1920

    def test_vertical_source_stays_vertical(self, tmp_path, reporter):
        video = make_video(tmp_path / "tall.mp4", 540, 960)
        out = VerticalRenderer(RenderSettings(preset="veryfast")).render(
            video, tmp_path / "out.mp4", reporter
        )
        assert (probe_video(out).width, probe_video(out).height) == (1080, 1920)

    @pytest.mark.parametrize("mode", ["blur", "black", "white", "crop"])
    def test_every_fill_mode_renders(self, tmp_path, reporter, mode):
        video = make_video(tmp_path / "wide.mp4", 1280, 720)
        out = VerticalRenderer(RenderSettings(fill_mode=mode, preset="veryfast")).render(
            video, tmp_path / f"out_{mode}.mp4", reporter
        )
        assert probe_video(out).height == 1920

    def test_source_metadata_is_removed(self, tmp_path, reporter):
        video = make_video(tmp_path / "src.mp4", 640, 480)
        tagged = tmp_path / "tagged.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c", "copy",
            "-metadata", "title=Nguon goc", "-metadata", "artist=Ai do", str(tagged),
        ], check=True)

        out = VerticalRenderer(RenderSettings(preset="veryfast")).render(
            tagged, tmp_path / "clean.mp4", reporter
        )
        tags = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags",
             "-of", "default=noprint_wrappers=1", str(out)],
            capture_output=True, text=True,
        ).stdout
        assert "Nguon goc" not in tags
        assert "Ai do" not in tags

    def test_custom_resolution_respected(self, tmp_path, reporter):
        video = make_video(tmp_path / "wide.mp4", 1280, 720)
        settings = RenderSettings(width=720, height=1280, preset="veryfast")
        out = VerticalRenderer(settings).render(video, tmp_path / "out.mp4", reporter)
        assert (probe_video(out).width, probe_video(out).height) == (720, 1280)

    def test_audio_survives_render(self, tmp_path, reporter):
        video = make_video(tmp_path / "wide.mp4", 1280, 720)
        out = VerticalRenderer(RenderSettings(preset="veryfast")).render(
            video, tmp_path / "out.mp4", reporter
        )
        streams = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True,
        ).stdout.strip()
        assert streams == "aac"
