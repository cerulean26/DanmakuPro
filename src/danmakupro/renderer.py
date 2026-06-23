"""弹幕渲染器模块

管理画布和 QPainter，渲染每帧的弹幕。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .models import ActiveDanmaku
from .layout_params import LayoutParams, LayerParams


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
        text_danmakus: list[ActiveDanmaku],
        gift_danmakus: list[ActiveDanmaku],
        layer_params: LayerParams,
        layout_params: LayoutParams,
        text_fade_out_zone: float,
        text_fade_out_threshold: float,
        gift_fade_out_zone: float,
        gift_fade_out_threshold: float,
    ) -> None:
        """渲染当前帧的所有弹幕到画布。

        先渲染礼物区（上方），再渲染文本区（下方），各自独立淡出。

        Args:
            text_danmakus: 当前活跃的文本弹幕列表
            gift_danmakus: 当前活跃的礼物弹幕列表
            layer_params: 渲染层参数
            layout_params: 布局参数
            text_fade_out_zone: 文本区淡出区域高度
            text_fade_out_threshold: 文本区淡出起始阈值
            gift_fade_out_zone: 礼物区淡出区域高度
            gift_fade_out_threshold: 礼物区淡出起始阈值
        """
        layer_y = layer_params.layer_y
        max_y_limit = layout_params.max_y_limit
        gift_y_limit = layout_params.gift_y_limit

        self.canvas.fill(Qt.GlobalColor.transparent)

        # 先渲染礼物区（上方）
        for dm in gift_danmakus:
            cy = dm.current_y
            alpha = 1.0

            if cy < gift_fade_out_threshold:
                if cy <= gift_y_limit:
                    continue
                else:
                    alpha = (cy - gift_y_limit) / gift_fade_out_zone
                    alpha = max(0.0, min(1.0, alpha))

            self.painter.setOpacity(alpha)
            local_x = dm.x - layer_params.layer_x
            local_y = int(dm.current_y) - layer_y
            dm.render(self.painter, local_x, local_y)

        # 再渲染文本区（下方）
        for dm in text_danmakus:
            cy = dm.current_y
            alpha = 1.0

            if cy < text_fade_out_threshold:
                if cy <= max_y_limit:
                    continue
                else:
                    alpha = (cy - max_y_limit) / text_fade_out_zone
                    alpha = max(0.0, min(1.0, alpha))

            self.painter.setOpacity(alpha)
            local_x = dm.x - layer_params.layer_x
            local_y = int(dm.current_y) - layer_y
            dm.render(self.painter, local_x, local_y)

    def get_frame_data(self) -> memoryview:
        """获取当前画布的原始像素数据。

        Returns:
            画布像素数据的 memoryview
        """
        return memoryview(self.canvas.bits())

    def end(self) -> None:
        """结束绘制，释放 QPainter 资源。"""
        self.painter.end()