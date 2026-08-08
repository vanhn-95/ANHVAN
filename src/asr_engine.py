"""Trích xuất phụ đề bằng Faster-Whisper + Silero VAD."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .progress import ProgressReporter
from .utils import PipelineError, Segment, module_available, probe_duration, resolve_device


class ASREngine:
    """Bọc faster-whisper, nạp model lazy và cache lại giữa các lần chạy."""

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "auto",
        compute_type: str = "auto",
        vad_filter: bool = True,
        models_dir: Optional[Path] = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.models_dir = Path(models_dir) if models_dir else None
        self._model = None

    @staticmethod
    def available() -> bool:
        return module_available("faster_whisper")

    def _resolve_compute_type(self, device: str) -> str:
        if self.compute_type != "auto":
            return self.compute_type
        return "float16" if device == "cuda" else "int8"

    def _load(self, reporter: ProgressReporter):
        if self._model is not None:
            return self._model
        if not self.available():
            raise PipelineError(
                "Thiếu faster-whisper nên không trích xuất được phụ đề. "
                "Cài bằng: pip install faster-whisper"
            )
        from faster_whisper import WhisperModel  # noqa: PLC0415

        device = resolve_device(self.device)
        compute_type = self._resolve_compute_type(device)
        reporter.log(f"Nạp model Whisper [{self.model_size}] - {device.upper()} / {compute_type}")
        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(self.models_dir) if self.models_dir else None,
        )
        return self._model

    def transcribe(
        self,
        audio: Path,
        reporter: ProgressReporter,
        language: str = "auto",
    ) -> List[Segment]:
        model = self._load(reporter)
        total = probe_duration(audio)

        reporter.log("Đang nhận dạng lời thoại...")
        segments_iter, info = model.transcribe(
            str(audio),
            language=None if language == "auto" else language,
            vad_filter=self.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500} if self.vad_filter else None,
            beam_size=5,
            condition_on_previous_text=False,
        )

        detected = getattr(info, "language", None)
        if detected:
            reporter.log(f"Ngôn ngữ nhận diện: {detected}")

        results: List[Segment] = []
        for raw in segments_iter:
            reporter.check_cancelled()
            text = (raw.text or "").strip()
            if not text:
                continue
            results.append(Segment(start=float(raw.start), end=float(raw.end), text=text))
            if total:
                reporter.progress(raw.end / total)

        if not results:
            raise PipelineError("Không nhận dạng được câu thoại nào trong video.")

        reporter.log(f"Đã trích xuất {len(results)} câu thoại.")
        reporter.progress(1.0)
        return results
