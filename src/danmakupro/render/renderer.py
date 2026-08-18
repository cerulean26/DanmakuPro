"""弹幕渲染器模块

提供单线程渲染模式，管理画布和 QPainter，渲染每帧的弹幕。
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from ..input.models import ActiveDanmaku
from ..layout.params import LayoutParams, LayerParams


class DanmakuRenderer:
    """弹幕渲染器：管理画布和 QPainter，渲染每帧的弹幕。

    职责：
        - 初始化画布和 QPainter
        - 渲染当前帧的所有弹幕（含淡出效果）
        - 管理画布生命周期
    """

    def __init__(self, layer_params: LayerParams):
        """初始化渲染器。
        Args:
            layer_params: 渲染层参数
        """
        self._layer_params = layer_params
        self.canvas = QImage(
            layer_params.layer_w, layer_params.layer_h,
            QImage.Format.Format_ARGB32,
        )
        self.painter = QPainter()
        self.painter.begin(self.canvas)
        self.painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    def render_frame(
        self,
        active_danmakus: Iterable[ActiveDanmaku],
        layout_params: LayoutParams,
        fade_out_zone: float,
    ) -> None:
        """渲染当前帧的所有弹幕到画布。

        包括淡出效果：弹幕接近屏幕顶部时逐渐透明，完全飞出时不可见。
        Args:
            active_danmakus: 当前活跃的弹幕列表
            layout_params: 布局参数
            fade_out_zone: 淡出区域高度（像素）
        """
        layer_y = self._layer_params.layer_y
        self.canvas.fill(Qt.GlobalColor.transparent)  # 清空画布

        for dm in active_danmakus:
            cy = dm.current_y

            alpha = 1.0
            if not dm.event.is_gift:
                limit = layout_params.text_top
                threshold = layout_params.text_top + fade_out_zone

                if cy < threshold:
                    if cy + dm.height <= limit:
                        continue
                    alpha = (cy - limit) / fade_out_zone
                    alpha = max(0.0, min(1.0, alpha))
            self.painter.setOpacity(alpha)
            local_x = dm.x - self._layer_params.layer_x
            local_y = int(dm.current_y) - layer_y
            dm.render(self.painter, int(local_x), local_y)

    def get_frame_data(self) -> bytes:
        """获取当前画布的原始像素数据（拷贝，生命周期安全）。

        Returns:
            画布像素数据的 bytes 副本
        """
        return bytes(self.canvas.bits())

    def end(self) -> None:
        """结束绘制，释放 QPainter 资源。"""
        self.painter.end()