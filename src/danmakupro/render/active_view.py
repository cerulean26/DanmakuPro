"""ActiveDanmakuView — Qt 渲染视图

包装 ActiveDanmaku 纯数据模型，提供 Qt 渲染能力。
通过 __getattr__ 代理所有数据属性访问，使外部代码无需感知包装层。
"""

from __future__ import annotations

from PySide6.QtGui import QImage, QPainter

from ..layout.active import ActiveDanmaku


class ActiveDanmakuView:
    """Qt-aware wrapper around ActiveDanmaku.

    职责：
        - 代理 ActiveDanmaku 的所有数据属性（通过 __getattr__）
        - 预渲染到 QImage 缓存 (pre_render)
        - 最终绘制 (render)
        - 缓存清理 (clear_cache)

    使用 __slots__ 以节省内存；__getattr__ 自动将未定义的属性访问
    转发到内部的 ActiveDanmaku 实例。
    """

    __slots__ = ('_dm', '_cached_image')

    def __init__(self, dm: ActiveDanmaku) -> None:
        self._dm = dm
        self._cached_image: QImage | None = None

    def __getattr__(self, name: str):
        return getattr(self._dm, name)

    def __setattr__(self, name: str, value) -> None:
        if name in ('_dm', '_cached_image'):
            super().__setattr__(name, value)
        else:
            setattr(self._dm, name, value)

    # -------------------------------------------------------------------------
    # 渲染
    # -------------------------------------------------------------------------

    def pre_render(
        self,
        font,
        emoji_cache: dict[str, QImage],
        gift_cache: dict[str, QImage],
        bg_color: tuple[int, int, int, int],
    ) -> None:
        """预渲染弹幕到缓存图片，委托给 DanmakuLayout。

        Args:
            font: 字体对象
            emoji_cache: Emoji 图片缓存
            gift_cache: 礼物图片缓存
            bg_color: 背景颜色 (r, g, b, a)
        """
        self._dm.layout.pre_render(font, emoji_cache, gift_cache, bg_color)
        self._cached_image = self._dm.layout.cached_image

    def render(self, painter: QPainter, x: int, y: int) -> None:
        """使用缓存的预渲染图片绘制弹幕。

        Args:
            painter: QPainter 对象
            x: 绘制 X 坐标
            y: 绘制 Y 坐标
        """
        if self._cached_image:
            painter.drawImage(x, y, self._cached_image)

    def clear_cache(self) -> None:
        """释放缓存的预渲染图片，显式触发 C++ 析构以立即释放像素缓冲区。"""
        self._cached_image = QImage()

    @property
    def cached_image(self) -> QImage | None:
        """预渲染缓存图片（测试/调试用）。"""
        return self._cached_image