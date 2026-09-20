"""弹幕渲染器模块

提供单线程渲染模式，管理画布和 QPainter，渲染每帧的弹幕。
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .active_view import ActiveDanmakuView
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
            layer_params.layer_w,
            layer_params.layer_h,
            QImage.Format.Format_ARGB32,
        )
        self.painter = QPainter()
        self.painter.begin(self.canvas)
        self.painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    def render_frame(
        self,
        active_text: Sequence[ActiveDanmakuView],
        active_gift: Sequence[ActiveDanmakuView],
        layout_params: LayoutParams,
        fade_out_zone: float,
    ) -> None:
        """渲染当前帧的所有弹幕到画布。

        包括淡出效果：弹幕接近屏幕顶部时逐渐透明，完全飞出时不可见。
        Args:
            active_text: 当前活跃的文本弹幕列表
            active_gift: 当前活跃的礼物弹幕列表
            layout_params: 布局参数
            fade_out_zone: 淡出区域高度（像素）。``<= 0`` 表示**关闭淡出**：
                弹幕保持全不透明，直到完全飞出 ``text_top`` 才消失（硬切）。
        """
        layer_y = self._layer_params.layer_y
        self.canvas.fill(Qt.GlobalColor.transparent)  # 清空画布

        limit = layout_params.text_top
        # zone = 0 时淡出区高度为 0，下面的 alpha 公式会除零；负数在配置层
        # 已被 _assert_non_negative 拦下，但本方法是公开入口，一并按 0 兜底。
        zone = max(0.0, fade_out_zone)
        threshold = limit + zone

        for dm in active_text:
            cy = dm.current_y
            alpha = 1.0
            if cy < threshold:
                if cy + dm.height <= limit:
                    continue
                if zone > 0:
                    alpha = (cy - limit) / zone
                    alpha = max(0.0, min(1.0, alpha))
            self.painter.setOpacity(alpha)
            local_x = dm.x - self._layer_params.layer_x
            local_y = int(dm.current_y) - layer_y
            dm.render(self.painter, int(local_x), local_y)

        for dm in active_gift:
            self.painter.setOpacity(1.0)
            local_x = dm.x - self._layer_params.layer_x
            local_y = int(dm.current_y) - layer_y
            dm.render(self.painter, int(local_x), local_y)

    def get_frame_data(self) -> memoryview:
        """获取当前画布的像素数据（**零拷贝别名视图，不是副本**）。

        返回的视图直接指向画布内存，下一次 ``render_frame()`` 开头的
        ``canvas.fill()`` 会就地改写这块内存，此前取到的内容随之改变。
        正确性依赖于调用方「同步写入完毕后再绘制下一帧」这一前提。

        Returns:
            画布像素数据的 memoryview 视图（仅在下一次 render_frame 前有效）

        为何采用视图、以及改为异步写入时必须如何调整，见
        ``docs/decisions/ADR-0005-zero-copy-frame-data.md``。
        """
        return memoryview(self.canvas.bits())

    def end(self) -> None:
        """结束绘制，释放 QPainter 资源。"""
        self.painter.end()