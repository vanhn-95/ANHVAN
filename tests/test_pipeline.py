"""Test cấu hình, kế hoạch pipeline và tiện ích SRT."""

from __future__ import annotations

import pytest

from src.config import AppSettings, JobConfig
from src.main_pipeline import plan_stages
from src.progress import ProgressReporter
from src.utils import CancelledError, Segment, format_timestamp, safe_filename, write_srt


class TestJobConfig:
    def test_valid_config_passes(self):
        JobConfig(source="https://youtu.be/abc", output_dir="/tmp/out").validate()

    def test_empty_source_rejected(self):
        with pytest.raises(ValueError, match="Chưa nhập nguồn"):
            JobConfig(source="").validate()

    def test_dubbing_requires_translation(self):
        config = JobConfig(source="x.mp4", translate=False, dubbing=True)
        with pytest.raises(ValueError, match="cần bật dịch thuật"):
            config.validate()

    def test_speed_ratio_bounds(self):
        with pytest.raises(ValueError, match="1.0 - 2.0"):
            JobConfig(source="x.mp4", max_speed_ratio=3.0).validate()

    def test_missing_speaker_file_rejected(self):
        config = JobConfig(source="x.mp4", tts_speaker_wav="/khong/ton/tai.wav")
        with pytest.raises(ValueError, match="giọng mẫu"):
            config.validate()

    def test_is_url(self):
        assert JobConfig(source="https://a.com/v").is_url()
        assert not JobConfig(source="/home/user/v.mp4").is_url()

    def test_roundtrip_dict(self):
        original = JobConfig(source="a.mp4", target_lang="en", whisper_model="small")
        restored = JobConfig.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_ignores_unknown_keys(self):
        restored = JobConfig.from_dict({"source": "a.mp4", "khong_ton_tai": 1})
        assert restored.source == "a.mp4"


class TestStagePlan:
    def test_full_pipeline_has_all_stages(self):
        keys = [s.key for s in plan_stages(JobConfig(source="a.mp4"))]
        assert keys == ["download", "separate", "asr", "translate", "tts", "render"]

    def test_subtitle_only_pipeline(self):
        config = JobConfig(source="a.mp4", translate=False, dubbing=False)
        keys = [s.key for s in plan_stages(config)]
        assert keys == ["download", "separate", "asr", "render"]

    def test_weights_are_positive(self):
        assert all(s.weight > 0 for s in plan_stages(JobConfig(source="a.mp4")))


class TestSrt:
    def test_format_timestamp(self):
        assert format_timestamp(0) == "00:00:00,000"
        assert format_timestamp(3661.5) == "01:01:01,500"
        assert format_timestamp(-5) == "00:00:00,000"

    def test_write_srt_uses_translation_when_asked(self, tmp_path):
        segments = [Segment(0.0, 1.5, "hello", "xin chào")]
        path = write_srt(segments, tmp_path / "out.srt", use_translation=True)
        content = path.read_text(encoding="utf-8")
        assert "xin chào" in content
        assert "00:00:00,000 --> 00:00:01,500" in content

    def test_write_srt_skips_empty_lines(self, tmp_path):
        segments = [Segment(0, 1, "a"), Segment(1, 2, "  "), Segment(2, 3, "b")]
        content = write_srt(segments, tmp_path / "o.srt").read_text(encoding="utf-8")
        assert content.count("-->") == 2

    def test_segment_duration_never_negative(self):
        assert Segment(5.0, 1.0, "x").duration == 0.0

    def test_output_text_prefers_translation(self):
        assert Segment(0, 1, "hi", "chào").output_text() == "chào"
        assert Segment(0, 1, "hi").output_text() == "hi"


class TestUtils:
    def test_safe_filename_strips_invalid_chars(self):
        assert safe_filename('a/b:c*d?') == "a_b_c_d"

    def test_safe_filename_keeps_vietnamese(self):
        assert safe_filename("Phim hài Việt Nam") == "Phim hài Việt Nam"

    def test_safe_filename_fallback(self):
        assert safe_filename("///") == "video"


class TestProgressReporter:
    def test_cancel_raises(self):
        reporter = ProgressReporter(on_log=lambda _: None)
        reporter.cancel()
        with pytest.raises(CancelledError):
            reporter.check_cancelled()

    def test_progress_scaled_into_stage_window(self):
        values = []
        reporter = ProgressReporter(on_log=lambda _: None, on_progress=values.append)
        reporter.begin_stage("Bước", 1, 2, base=0.5, weight=0.25)
        reporter.progress(0.5)
        reporter.end_stage()
        assert values == [0.5, 0.625, 0.75]

    def test_progress_clamped(self):
        values = []
        reporter = ProgressReporter(on_log=lambda _: None, on_progress=values.append)
        reporter.begin_stage("Bước", 1, 1, base=0.0, weight=1.0)
        reporter.progress(5.0)
        reporter.progress(-1.0)
        assert values[1:] == [1.0, 0.0]


class TestAppSettings:
    def test_save_and_load(self, tmp_path):
        settings = AppSettings()
        settings.last_job = JobConfig(source="a.mp4", target_lang="en")
        settings.remember_source("a.mp4")
        settings.save(tmp_path / "s.json")

        loaded = AppSettings.load(tmp_path / "s.json")
        assert loaded.last_job.target_lang == "en"
        assert loaded.recent_sources == ["a.mp4"]

    def test_load_missing_file_returns_defaults(self, tmp_path):
        assert AppSettings.load(tmp_path / "khong-co.json").recent_sources == []

    def test_recent_sources_deduplicated_and_capped(self):
        settings = AppSettings()
        for i in range(15):
            settings.remember_source(f"v{i}.mp4")
        settings.remember_source("v14.mp4")
        assert len(settings.recent_sources) == 10
        assert settings.recent_sources[0] == "v14.mp4"
