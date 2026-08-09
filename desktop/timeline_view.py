"""Timeline sơ lược bằng QGraphicsScene: 3 track xếp dọc theo thời gian.

Chỉ để nhìn bố cục thời gian trước khi chạy Bot - không kéo thả, không cắt ghép.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QSizePolicy

from src.intro_maker import INTRO_SECONDS

# Màu từng track theo đúng yêu cầu: video xanh, giọng vàng, nhạc cam.
COLOR_VIDEO = "#4f8cff"
COLOR_VOICE = "#f5b544"
COLOR_MUSIC = "#ff8a3d"
COLOR_INTRO = "#a06cff"
COLOR_GRID = "#2e3441"
COLOR_TEXT = "#8b93a7"
COLOR_BG = "#0f1116"

TRACK_HEIGHT = 34
TRACK_GAP = 10
RULER_HEIGHT = 22
LABEL_WIDTH = 132
SIDE_PADDING = 12
MIN_DURATION = 10.0        # timeline trống vẫn vẽ khung 10 giây cho dễ hình dung


@dataclass
class Clip:
    """Một khối trên timeline: bắt đầu, dài bao lâu, nhãn, màu."""

    start: float
    duration: float
    label: str
    color: str

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Track:
    name: str
    clips: List[Clip]


class TimelineView(QGraphicsView):
    """Vẽ 3 track: video gốc, giọng đọc mới, nhạc nền mới."""

    def __init__(self, parent=None) -> None:
        # super() phải chạy trước: PySide6 cấm dùng `self` làm parent của QObject
        # khi lớp cơ sở chưa khởi tạo xong.
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.total_duration = 0.0
        self.tracks: List[Track] = []

        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QBrush(QColor(COLOR_BG)))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(RULER_HEIGHT + 3 * TRACK_HEIGHT + 3 * TRACK_GAP + 12)

        self.set_layout(0.0)

    # ------------------------------------------------------------------ dữ liệu
    def set_layout(
        self,
        duration: float,
        has_intro: bool = False,
        has_voice: bool = False,
        has_music: bool = False,
        intro_seconds: float = INTRO_SECONDS,
    ) -> None:
        """Dựng lại timeline theo cấu hình hiện tại của Bot."""
        body = max(0.0, duration)
        intro = intro_seconds if has_intro else 0.0
        self.total_duration = max(intro + body, MIN_DURATION if body <= 0 else intro + body)

        video_clips: List[Clip] = []
        if intro:
            video_clips.append(Clip(0.0, intro, f"Intro {intro:.0f}s", COLOR_INTRO))
        if body:
            video_clips.append(Clip(intro, body, "Video gốc", COLOR_VIDEO))

        voice_clips = [Clip(intro, body, "Giọng đọc mới (TTS)", COLOR_VOICE)] \
            if has_voice and body else []
        music_clips = [Clip(intro, body, "Nhạc nền mới", COLOR_MUSIC)] \
            if has_music and body else []

        self.tracks = [
            Track("Video", video_clips),
            Track("Giọng nói", voice_clips),
            Track("Nhạc nền", music_clips),
        ]
        self._redraw()

    # -------------------------------------------------------------------- vẽ
    def _redraw(self) -> None:
        self._scene.clear()
        width = max(360, self.viewport().width())
        track_width = width - LABEL_WIDTH - SIDE_PADDING * 2
        if track_width <= 0:
            return

        self._scene.setSceneRect(0, 0, width, self.height())
        seconds = max(self.total_duration, MIN_DURATION)
        pen_none = QPen(Qt.NoPen)

        # --- thước thời gian ---
        step = _ruler_step(seconds)
        tick = 0.0
        while tick <= seconds + 0.01:
            x = LABEL_WIDTH + SIDE_PADDING + (tick / seconds) * track_width
            line = self._scene.addLine(x, RULER_HEIGHT - 6, x, self.height() - 6,
                                       QPen(QColor(COLOR_GRID), 1))
            line.setZValue(-1)
            text = self._scene.addText(_format_seconds(tick), QFont("", 7))
            text.setDefaultTextColor(QColor(COLOR_TEXT))
            text.setPos(x - 12, 0)
            tick += step

        # --- từng track ---
        for index, track in enumerate(self.tracks):
            top = RULER_HEIGHT + index * (TRACK_HEIGHT + TRACK_GAP)

            label = self._scene.addText(track.name, QFont("", 8))
            label.setDefaultTextColor(QColor(COLOR_TEXT))
            label.setPos(SIDE_PADDING, top + TRACK_HEIGHT / 2 - 10)

            lane = self._scene.addRect(
                QRectF(LABEL_WIDTH + SIDE_PADDING, top, track_width, TRACK_HEIGHT),
                QPen(QColor(COLOR_GRID), 1), QBrush(QColor("#161922")),
            )
            lane.setZValue(-2)

            for clip in track.clips:
                x = LABEL_WIDTH + SIDE_PADDING + (clip.start / seconds) * track_width
                clip_width = max(3.0, (clip.duration / seconds) * track_width)
                colour = QColor(clip.color)

                block = self._scene.addRect(
                    QRectF(x, top + 2, clip_width, TRACK_HEIGHT - 4),
                    pen_none, QBrush(colour),
                )
                block.setToolTip(
                    f"{clip.label}: {_format_seconds(clip.start)} → {_format_seconds(clip.end)}"
                )

                if clip_width > 70:
                    caption = self._scene.addText(clip.label, QFont("", 8))
                    caption.setDefaultTextColor(QColor("#10131a"))
                    caption.setPos(x + 6, top + TRACK_HEIGHT / 2 - 11)
                    caption.setZValue(1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redraw()

    # ------------------------------------------------------------- tiện ích test
    def clip_labels(self) -> List[str]:
        return [clip.label for track in self.tracks for clip in track.clips]


def _ruler_step(seconds: float) -> float:
    """Chọn bước chia thước sao cho ra khoảng 6-10 vạch."""
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if seconds / step <= 10:
            return float(step)
    return 900.0


def _format_seconds(value: float) -> str:
    total = int(round(value))
    return f"{total // 60}:{total % 60:02d}"
