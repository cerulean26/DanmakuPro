"""活跃弹幕节点

存储当前屏幕上一条弹幕的运行时状态，由 LayoutEngine 管理生命周期。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QColor, QImage, QPainter

if TYPE_CHECKING:
    from ..input.event import DanmakuEvent
    from ..render.layout_builder import DanmakuLayout
    from ..render.segments import TextRow


class ActiveDanmaku:
    """活跃弹幕节点：存储当前屏幕上一条弹幕的运行时状态。

    职责：
        - 持有弹幕事件和布局数据
        - 管理位置状态（current_y、target_y）
        - 越界检测 (is_out_of_bounds)
        - 委托渲染给 DanmakuLayout

    段落解析、折行、尺寸计算、预渲染等构造阶段逻辑已提取至
    DanmakuLayoutBuilder 和 DanmakuLayout。

    使用 __slots__ 而非 __dict__ 以节省内存。
    """

    __slots__ = [
        'event', 'current_y', 'target_y', 'x',
        'layout', 'is_locked_to_next', 'is_first_activation', 'spawn_time',
    ]

    COLOR_NORMAL_PREFIX = QColor(135, 206, 250)
    COLOR_WHITE = QColor(255, 255, 255)
    COLOR_GIFT_TEXT = QColor(255, 255, 150)

    def __init__(
        self,
        event: DanmakuEvent,
        layout: DanmakuLayout,
        x: int = 0,
    ):
        """初始化活跃弹幕节点。

        Args:
            event: 弹幕事件数据
            layout: 预构建的弹幕布局（由 DanmakuLayoutBuilder 生成）
            x: 弹幕/渲染层 X 偏移
        """
        self.event = event
        self.layout = layout
        self.current_y = 0.0
        self.target_y = 0.0
        self.x = x
        self.is_locked_to_next = False
        self.is_first_activation = True
        self.spawn_time = 0.0

    # -------------------------------------------------------------------------
    # 属性代理：委托给 DanmakuLayout
    # -------------------------------------------------------------------------

    @property
    def height(self) -> int:
        return self.layout.height

    @property
    def rows(self) -> list[TextRow]:
        return self.layout.rows

    @property
    def total_width(self) -> int:
        return self.layout.total_width

    @property
    def radius(self) -> float:
        return self.layout.radius

    @property
    def cached_image(self) -> QImage | None:
        return self.layout.cached_image

    @cached_image.setter
    def cached_image(self, value: QImage | None) -> None:
        self.layout.cached_image = value

    # -------------------------------------------------------------------------
    # 渲染委托
    # -------------------------------------------------------------------------

    def pre_render(
        self,
        font,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        bg_color: QColor,
    ) -> None:
        """预渲染弹幕到缓存图片，委托给 DanmakuLayout。"""
        self.layout.pre_render(font, emoji_cache, gift_cache, bg_color)

    def render(self, painter: QPainter, x: int, y: int) -> None:
        """使用缓存的预渲染图片绘制弹幕，委托给 DanmakuLayout。"""
        self.layout.render(painter, x, y)

    # -------------------------------------------------------------------------
    # 越界检测
    # -------------------------------------------------------------------------

    def is_out_of_bounds(self, max_y_limit: float) -> bool:
        """判断弹幕是否已经完全飞出屏幕顶部。

        Args:
            max_y_limit: 弹幕区顶部 Y 坐标（低于此值视为越界）

        Returns:
            True 表示弹幕已完全不可见，可以回收
        """
        return self.current_y + self.layout.height <= max_y_limit