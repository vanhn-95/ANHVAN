"""Test các module Auto Creator: intro, kịch bản, nhạc, pipeline."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from src.creator_pipeline import CreatorConfig, plan_stages
from src.intro_maker import (
    BACKGROUNDS,
    FALLBACK_TEXT,
    IntroMaker,
    VideoInfo,
    default_intro_from_segments,
    escape_drawtext,
    find_font,
    wrap_text,
)
from src.music_mixer import MusicMixer, list_library, pick_music, validate_music_file
from src.script_writer import (
    FALLBACK_GENRES,
    MOODS,
    TIKTOK_SCRIPT_PROMPT,
    MoodResult,
    clean_intro,
    ensure_punctuation,
    extract_json,
    resolve_intro_text,
    script_preview,
)
from src.progress import ProgressReporter
from src.utils import PipelineError, Segment

has_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="Cần FFmpeg")


@pytest.fixture
def reporter():
    return ProgressReporter(on_log=lambda _: None)


@pytest.fixture
def segments():
    return [
        Segment(0.0, 2.0, "This soup is amazing", "Món canh này ngon xuất sắc"),
        Segment(2.0, 4.0, "Let me show you how", "Để tôi chỉ bạn cách làm"),
    ]


# ------------------------------------------------------------------------- intro
class TestDrawtextEscaping:
    def test_escapes_colon(self):
        assert escape_drawtext("Giá: 50") == r"Giá\: 50"

    def test_escapes_quote(self):
        assert escape_drawtext("it's") == r"it\'s"

    def test_escapes_percent(self):
        assert escape_drawtext("50%") == r"50\%"

    def test_escapes_backslash(self):
        assert "\\\\" in escape_drawtext("a\\b")

    def test_plain_text_untouched(self):
        assert escape_drawtext("MẸO HAY MỖI NGÀY") == "MẸO HAY MỖI NGÀY"


class TestWrapText:
    def test_short_text_one_line(self):
        assert wrap_text("MẸO HAY") == ["MẸO HAY"]

    def test_wraps_on_word_boundary(self):
        lines = wrap_text("REVIEW MỸ PHẨM CỰC CHẤT", max_chars=16)
        assert len(lines) == 2
        assert all(len(line) <= 16 for line in lines)
        assert " ".join(lines) == "REVIEW MỸ PHẨM CỰC CHẤT"

    def test_caps_at_three_lines(self):
        assert len(wrap_text(" ".join(["TU"] * 40))) == 3

    def test_empty_uses_fallback(self):
        assert wrap_text("   ") == [FALLBACK_TEXT]


class TestIntroFilter:
    def test_filter_mentions_font_and_text(self, tmp_path):
        if not find_font():
            pytest.skip("Máy không có font nào")
        graph = IntroMaker(tmp_path).build_filter("MẸO HAY", VideoInfo(1080, 1920, 30))
        assert "drawtext" in graph
        assert "zoompan" in graph
        assert "MẸO HAY" in graph
        assert "[vout]" in graph and "[aout]" in graph

    def test_font_size_shrinks_for_long_text(self, tmp_path):
        if not find_font():
            pytest.skip("Máy không có font nào")
        maker = IntroMaker(tmp_path)
        info = VideoInfo(1080, 1920, 30)
        short = maker.build_filter("HOT", info)
        long = maker.build_filter("REVIEW MỸ PHẨM CỰC CHẤT HÔM NAY", info)

        def size(graph: str) -> int:
            import re
            return max(int(m) for m in re.findall(r"fontsize=(\d+)", graph))

        assert size(short) > size(long)

    def test_unknown_background_falls_back(self, tmp_path):
        assert IntroMaker(tmp_path, "mau-la").background in BACKGROUNDS


class TestDefaultIntro:
    def test_uses_first_segment(self, segments):
        text = default_intro_from_segments(segments)
        assert text == text.upper()
        assert "MÓN CANH" in text

    def test_empty_segments(self):
        assert default_intro_from_segments([]) == FALLBACK_TEXT


@has_ffmpeg
class TestIntroRender:
    def _sample(self, tmp_path: Path) -> Path:
        import subprocess

        path = tmp_path / "src.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=360x640:rate=15:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
            "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path),
        ], check=True)
        return path

    def test_builds_three_second_intro(self, tmp_path, reporter):
        from src.utils import probe_duration

        if not find_font():
            pytest.skip("Máy không có font nào")
        video = self._sample(tmp_path)
        intro = IntroMaker(tmp_path / "ws").build("XIN CHÀO", video, reporter)

        assert intro.exists()
        assert 2.8 <= probe_duration(intro) <= 3.2

    def test_intro_matches_source_resolution(self, tmp_path, reporter):
        from src.intro_maker import probe_video

        if not find_font():
            pytest.skip("Máy không có font nào")
        video = self._sample(tmp_path)
        intro = IntroMaker(tmp_path / "ws").build("TEST", video, reporter)

        assert probe_video(intro).width == probe_video(video).width

    def test_prepend_adds_three_seconds(self, tmp_path, reporter):
        from src.utils import probe_duration

        if not find_font():
            pytest.skip("Máy không có font nào")
        video = self._sample(tmp_path)
        maker = IntroMaker(tmp_path / "ws")
        intro = maker.build("TEST", video, reporter)
        merged = maker.prepend(intro, video, tmp_path / "out.mp4", reporter)

        assert probe_duration(merged) == pytest.approx(probe_duration(video) + 3.0, abs=0.4)


# ------------------------------------------------------------------ script writer
class TestPrompt:
    def test_contains_user_requirements(self):
        for phrase in ["Content Creator TikTok", "Gen Z", "câu hỏi tu từ", "dấu chấm than"]:
            assert phrase in TIKTOK_SCRIPT_PROMPT

    def test_enforces_line_count(self):
        assert "{count}" in TIKTOK_SCRIPT_PROMPT
        assert "KHÔNG gộp dòng" in TIKTOK_SCRIPT_PROMPT


class TestPunctuation:
    @pytest.mark.parametrize("text,expected", [
        ("Ngon quá", "Ngon quá."),
        ("Ngon quá!", "Ngon quá!"),
        ("Thật à?", "Thật à?"),
        ("Chờ đã…", "Chờ đã…"),
    ])
    def test_adds_only_when_missing(self, text, expected):
        assert ensure_punctuation(text) == expected

    def test_empty_stays_empty(self):
        assert ensure_punctuation("  ") == ""


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"mood": "Buồn"}')["mood"] == "Buồn"

    def test_fenced_json(self):
        assert extract_json('```json\n{"mood": "Vui"}\n```')["mood"] == "Vui"

    def test_json_with_prose_around(self):
        raw = 'Đây là kết quả:\n{"mood": "Sôi động"}\nHết.'
        assert extract_json(raw)["mood"] == "Sôi động"

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            extract_json("không có json ở đây")

    def test_non_object_raises(self):
        with pytest.raises(ValueError):
            extract_json("[1, 2, 3]")


class TestCleanIntro:
    def test_strips_quotes_and_uppercases(self):
        assert clean_intro('"món ngon cực đỉnh"') == "MÓN NGON CỰC ĐỈNH"

    def test_removes_emoji(self):
        assert "🔥" not in clean_intro("HOT 🔥 QUÁ")

    def test_caps_word_count(self):
        assert len(clean_intro("một hai ba bốn năm sáu bảy").split()) == 5

    def test_strips_label_prefix(self):
        assert clean_intro("Intro: MÓN NGON") == "MÓN NGON"

    def test_takes_first_line_only(self):
        assert clean_intro("MÓN NGON\nlời giải thích") == "MÓN NGON"

    def test_empty_input(self):
        assert clean_intro("") == ""


class TestMoodResult:
    def test_default_genres_filled(self):
        assert MoodResult(mood="Buồn").genres == FALLBACK_GENRES["Buồn"]

    def test_every_mood_has_genres(self):
        for mood in MOODS:
            assert FALLBACK_GENRES[mood]


class TestScriptPreview:
    def test_joins_translated_text(self, segments):
        preview = script_preview(segments)
        assert "Món canh này ngon xuất sắc" in preview
        assert "Để tôi chỉ bạn cách làm" in preview

    def test_respects_limit(self, segments):
        assert len(script_preview(segments, limit=10)) < 60


class TestResolveIntroText:
    def test_manual_wins(self, segments, reporter):
        text = resolve_intro_text("KÊNH CỦA TÔI", True, None, segments, reporter)
        assert text == "KÊNH CỦA TÔI"

    def test_falls_back_to_first_segment_without_ai(self, segments, reporter):
        text = resolve_intro_text("", True, None, segments, reporter)
        assert "MÓN CANH" in text

    def test_uses_ai_suggestion(self, segments, reporter):
        class FakeWriter:
            def suggest_intro(self, segs, rep):
                return "CỰC PHẨM MÓN ĂN"

        assert resolve_intro_text("", True, FakeWriter(), segments, reporter) == "CỰC PHẨM MÓN ĂN"

    def test_ai_disabled_skips_writer(self, segments, reporter):
        class BoomWriter:
            def suggest_intro(self, segs, rep):
                raise AssertionError("không được gọi AI khi tắt")

        assert resolve_intro_text("", False, BoomWriter(), segments, reporter)


# -------------------------------------------------------------------------- nhạc
class TestMusicLibrary:
    def test_empty_folder(self, tmp_path):
        choice = pick_music(["lofi"], tmp_path)
        assert not choice.found
        assert "trống" in choice.reason

    def test_matches_genre_in_filename(self, tmp_path):
        (tmp_path / "lofi-chill.mp3").touch()
        (tmp_path / "edm-hype.mp3").touch()

        choice = pick_music(["lofi"], tmp_path)
        assert choice.found
        assert choice.path.name == "lofi-chill.mp3"
        assert choice.matched_genre == "lofi"

    def test_matching_ignores_vietnamese_accents(self, tmp_path):
        (tmp_path / "nhac-buon-piano.mp3").touch()
        choice = pick_music(["buồn"], tmp_path)
        assert choice.found

    def test_random_when_no_match(self, tmp_path):
        (tmp_path / "abc.mp3").touch()
        choice = pick_music(["khong-co-the-loai-nay"], tmp_path, random.Random(1))
        assert choice.found
        assert "ngẫu nhiên" in choice.reason

    def test_ignores_non_audio_files(self, tmp_path):
        (tmp_path / "README.md").touch()
        (tmp_path / "cover.jpg").touch()
        assert list_library(tmp_path) == []

    def test_first_genre_has_priority(self, tmp_path):
        (tmp_path / "piano-sad.mp3").touch()
        (tmp_path / "edm-party.mp3").touch()
        assert pick_music(["edm", "piano"], tmp_path).path.name == "edm-party.mp3"


class TestValidateMusicFile:
    def test_missing_file(self, tmp_path):
        with pytest.raises(PipelineError, match="Không tìm thấy"):
            validate_music_file(str(tmp_path / "khong-co.mp3"))

    def test_wrong_extension(self, tmp_path):
        bad = tmp_path / "nhac.txt"
        bad.touch()
        with pytest.raises(PipelineError, match="không hỗ trợ"):
            validate_music_file(str(bad))

    def test_accepts_supported(self, tmp_path):
        good = tmp_path / "nhac.mp3"
        good.touch()
        assert validate_music_file(str(good)) == good


@has_ffmpeg
class TestMusicMixing:
    def _tone(self, path: Path, freq: int, seconds: float = 3.0) -> Path:
        import subprocess

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-ar", "44100", "-ac", "2", str(path),
        ], check=True)
        return path

    def test_mix_produces_audio(self, tmp_path, reporter):
        from src.utils import probe_duration

        voice = self._tone(tmp_path / "voice.wav", 440)
        music = self._tone(tmp_path / "music.wav", 200, 1.0)

        mixed = MusicMixer(tmp_path / "ws").mix(voice, music, reporter, duration=3.0)
        assert mixed.exists()
        assert probe_duration(mixed) == pytest.approx(3.0, abs=0.3)

    def test_short_music_loops_to_cover_video(self, tmp_path, reporter):
        """Nhạc 1 giây phải lặp để phủ hết video 3 giây."""
        from src.utils import probe_duration

        voice = self._tone(tmp_path / "voice.wav", 440, 3.0)
        music = self._tone(tmp_path / "music.wav", 200, 1.0)

        mixed = MusicMixer(tmp_path / "ws").mix(voice, music, reporter, duration=3.0)
        assert probe_duration(mixed) == pytest.approx(3.0, abs=0.3)

    def test_no_music_returns_voice_untouched(self, tmp_path, reporter):
        voice = self._tone(tmp_path / "voice.wav", 440)
        assert MusicMixer(tmp_path / "ws").mix(voice, None, reporter) == voice

    def test_ducking_off_still_mixes(self, tmp_path, reporter):
        voice = self._tone(tmp_path / "voice.wav", 440)
        music = self._tone(tmp_path / "music.wav", 200)

        mixed = MusicMixer(tmp_path / "ws", ducking=False).mix(voice, music, reporter)
        assert mixed.exists()


# ---------------------------------------------------------------------- cấu hình
class TestCreatorConfig:
    def test_valid(self):
        CreatorConfig(source="https://v.douyin.com/abc", api_key="k").validate()

    def test_requires_source(self):
        with pytest.raises(ValueError, match="link video"):
            CreatorConfig(api_key="k").validate()

    def test_rewrite_requires_api_key(self):
        with pytest.raises(ValueError, match="API key"):
            CreatorConfig(source="a.mp4", rewrite_script=True, api_key="").validate()

    def test_no_key_needed_when_ai_off(self):
        CreatorConfig(
            source="a.mp4", rewrite_script=False, intro_auto_ai=False, api_key=""
        ).validate()

    def test_rejects_unknown_provider(self):
        with pytest.raises(ValueError, match="Nhà cung cấp"):
            CreatorConfig(source="a.mp4", api_key="k", provider="claude").validate()

    def test_music_db_bounds(self):
        with pytest.raises(ValueError, match="-40dB"):
            CreatorConfig(source="a.mp4", api_key="k", music_db=5.0).validate()

    def test_roundtrip(self):
        original = CreatorConfig(source="a.mp4", intro_text="HOT", music_db=-12.0)
        assert CreatorConfig.from_dict(original.to_dict()) == original

    def test_from_app_config_takes_provider_and_key(self, tmp_path):
        from src.app_config import AppConfig

        app_config = AppConfig.load(tmp_path / "config.ini")
        app_config.provider = "deepseek"
        app_config.set_api_key_for("deepseek", "sk-ds")

        config = CreatorConfig.from_app_config(app_config)
        assert config.provider == "deepseek"
        assert config.api_key == "sk-ds"


class TestStagePlan:
    def test_full_run(self):
        keys = [s.key for s in plan_stages(CreatorConfig())]
        assert keys == ["download", "separate", "asr", "rewrite", "mood",
                        "tts", "mix", "intro", "render"]

    def test_everything_optional_off(self):
        config = CreatorConfig(
            rewrite_script=False, add_music=False, tts_dubbing=False, make_intro=False
        )
        assert [s.key for s in plan_stages(config)] == [
            "download", "separate", "asr", "mix", "render"
        ]

    def test_weights_positive(self):
        assert all(s.weight > 0 for s in plan_stages(CreatorConfig()))

    def test_stage_labels_are_vietnamese(self):
        for stage in plan_stages(CreatorConfig()):
            assert stage.label.strip()
