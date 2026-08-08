"""Tải video từ URL (yt-dlp) hoặc nhận file local."""

from __future__ import annotations

import shutil
from pathlib import Path

from .progress import ProgressReporter
from .utils import PipelineError, module_available, safe_filename


class MediaDownloader:
    """Đưa nguồn đầu vào (URL hoặc file) về một file video trong workspace."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def available() -> bool:
        return module_available("yt_dlp")

    def fetch(self, source: str, reporter: ProgressReporter) -> Path:
        source = source.strip()
        if source.lower().startswith(("http://", "https://")):
            return self._download(source, reporter)
        return self._copy_local(source, reporter)

    def _copy_local(self, source: str, reporter: ProgressReporter) -> Path:
        src = Path(source).expanduser()
        if not src.is_file():
            raise PipelineError(f"Không tìm thấy file video: {src}")
        target = self.workspace / f"source{src.suffix or '.mp4'}"
        if src.resolve() == target.resolve():
            return target
        reporter.log(f"Dùng file local: {src.name}")
        shutil.copy2(src, target)
        reporter.progress(1.0)
        return target

    def _download(self, url: str, reporter: ProgressReporter) -> Path:
        if not self.available():
            raise PipelineError(
                "Thiếu yt-dlp nên không tải được video từ URL. "
                "Cài bằng: pip install yt-dlp"
            )
        import yt_dlp  # noqa: PLC0415

        def hook(status: dict) -> None:
            reporter.check_cancelled()
            if status.get("status") != "downloading":
                return
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            if total:
                reporter.progress(done / total)

        options = {
            "outtmpl": str(self.workspace / "source.%(ext)s"),
            "format": "bestvideo[height<=1080]+bestaudio/best",
            "merge_output_format": "mp4",
            "noprogress": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
        }

        reporter.log(f"Đang tải video: {url}")
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded = Path(ydl.prepare_filename(info))
        except Exception as exc:  # yt-dlp ném nhiều loại lỗi mạng khác nhau
            raise PipelineError(f"Tải video thất bại: {exc}") from exc

        if not downloaded.exists():
            merged = downloaded.with_suffix(".mp4")
            if not merged.exists():
                raise PipelineError("yt-dlp báo thành công nhưng không thấy file kết quả.")
            downloaded = merged

        title = safe_filename(str(info.get("title", "video")))
        reporter.log(f"Đã tải xong: {title}")
        reporter.progress(1.0)
        return downloaded
