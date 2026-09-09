"""后台编码工作线程

BurnWorker 在 QThread 中运行 DanmakuBurner，通过信号向 UI 报告进度。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ..core.burner import DanmakuBurner
from ..config.models import DanmakuConfig


class BurnWorker(QThread):
    """后台编码线程"""

    progress = Signal(int, int)
    speed = Signal(float)
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(
        self,
        video_in: str,
        xml_in: str,
        video_out: str,
        encode_mode: str,
        config: DanmakuConfig,
        parent: QThread | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_in = video_in
        self._xml_in = xml_in
        self._video_out = video_out
        self._encode_mode = encode_mode
        self._config = config
        self._stop_event = threading.Event()
        self._burner: DanmakuBurner | None = None

    def stop(self) -> None:
        """请求停止编码"""
        self._stop_event.set()

    def force_stop(self) -> None:
        """强制停止：关闭 FFmpeg stdin 解除阻塞"""
        self._stop_event.set()
        if self._burner is not None:
            self._burner.force_stop()

    def run(self) -> None:
        try:
            self._burner = DanmakuBurner(
                video_in=self._video_in,
                xml_in=self._xml_in,
                video_out=self._video_out,
                encode_mode=self._encode_mode,
                config=self._config,
                force=True,
            )
            self._burner.run(
                progress_callback=self._on_progress,
                speed_callback=self._on_speed,
                log_callback=self._on_log,
                stop_check=self._stop_event.is_set,
            )
            if self._stop_event.is_set():
                self.finished.emit(False, "STOPPED")
            else:
                self.finished.emit(True, "压制完成")
        except Exception as e:
            if self._stop_event.is_set():
                self.finished.emit(False, "STOPPED")
            else:
                self.finished.emit(False, str(e))

    def _on_progress(self, current: int, total: int) -> None:
        self.progress.emit(current, total)

    def _on_speed(self, value: float) -> None:
        self.speed.emit(value)

    def _on_log(self, message: str) -> None:
        self.log.emit(message)