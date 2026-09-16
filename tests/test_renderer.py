"""renderer.py 单元测试

测试 DanmakuRenderer 的初始化、帧渲染（含淡出）、帧数据获取和资源释放。

注意：渲染器使用真实的 QPainter。淡出逻辑既通过 render 方法是否被调用来
间接验证，也在需要精确核对透明度时对 painter 实例打桩，直接断言
setOpacity 收到的 alpha（`patch.object(renderer.painter, "setOpacity")`）。
"""

import contextlib
from unittest.mock import MagicMock, call, patch

from PySide6.QtGui import QImage

from danmakupro.render.renderer import DanmakuRenderer
from danmakupro.layout.params import LayoutParams, LayerParams


# =============================================================================
# 测试辅助
# =============================================================================


@contextlib.contextmanager
def _renderer(layer_params: LayerParams):
    """渲染器上下文：无论断言是否失败都保证调用 end()。

    不是洁癖：若 render_frame 抛异常而 end() 未被调用，QPainter 会带着活跃
    状态与画布一起被回收，整个 pytest 进程直接 ACCESS_VIOLATION
    （实测 exit=3221225477），只剩「进程崩了」、看不到是哪条用例挂的。
    产品路径有 finally 兜底（core/pipeline.py:165-167），测试需自己保证。
    """
    renderer = DanmakuRenderer(layer_params)
    try:
        yield renderer
    finally:
        renderer.end()


def _layer_params(
    layer_w: int = 800,
    layer_h: int = 600,
    layer_x: int = 20,
    layer_y: int = 0,
) -> LayerParams:
    return LayerParams(
        layer_x=layer_x,
        layer_y=layer_y,
        layer_w=layer_w,
        layer_h=layer_h,
    )


def _layout_params(
    bottom: int = 1000,
    text_h: int = 400,
    text_top: int = 600,
    text_w: int = 800,
    gap: int = 4,
    gift_top: int = 400,
    gift_h: int = 200,
) -> LayoutParams:
    return LayoutParams(
        bottom=bottom,
        text_h=text_h,
        text_top=text_top,
        text_w=text_w,
        gap=gap,
        gift_top=gift_top,
        gift_h=gift_h,
    )


def _make_stub_dm(current_y: float = 800.0, height: int = 50, x: int = 20):
    """创建最小化桩对象，满足 render_frame 所需的属性。"""
    dm = MagicMock()
    dm.current_y = current_y
    dm.height = height
    dm.x = x
    return dm


# =============================================================================
# 初始化
# =============================================================================


class TestInit:
    """测试 DanmakuRenderer 初始化。"""

    def test_canvas_created(self):
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        assert renderer.canvas is not None
        assert renderer.canvas.width() == 800
        assert renderer.canvas.height() == 600
        assert renderer.canvas.format() == QImage.Format.Format_ARGB32
        renderer.end()

    def test_painter_active(self):
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        assert renderer.painter.isActive()
        renderer.end()


# =============================================================================
# render_frame
# =============================================================================


class TestRenderFrame:
    """测试 render_frame：空列表、正常渲染、淡出效果、坐标计算。"""

    def test_empty_lists(self):
        """空列表不应抛出异常。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        renderer.render_frame([], [], _layout_params(), fade_out_zone=50.0)
        renderer.end()

    def test_text_danmaku_renders(self):
        """文本弹幕应调用 render 方法。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        dm = _make_stub_dm(current_y=800.0, height=50, x=20)

        renderer.render_frame([dm], [], _layout_params(), fade_out_zone=50.0)

        dm.render.assert_called_once()
        renderer.end()

    def test_gift_danmaku_renders(self):
        """礼物弹幕应调用 render 方法。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        dm = _make_stub_dm(current_y=700.0, height=50, x=20)

        renderer.render_frame([], [dm], _layout_params(), fade_out_zone=50.0)

        dm.render.assert_called_once()
        renderer.end()

    def test_text_and_gift_both_rendered(self):
        """文本和礼物弹幕应分别渲染。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        text_dm = _make_stub_dm(current_y=800.0, height=50, x=20)
        gift_dm = _make_stub_dm(current_y=700.0, height=50, x=20)

        renderer.render_frame(
            [text_dm], [gift_dm], _layout_params(), fade_out_zone=50.0
        )

        text_dm.render.assert_called_once()
        gift_dm.render.assert_called_once()
        renderer.end()

    def test_text_in_fade_out_zone_still_rendered(self):
        """文本弹幕在淡出区域内但仍部分可见时，应被渲染（opacity < 1）。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=620.0, height=50, x=20)
        # cy=620 < threshold=650, cy+height=670 > limit=600 → 部分可见

        renderer.render_frame([dm], [], layout, fade_out_zone=50.0)

        dm.render.assert_called_once()
        renderer.end()

    def test_text_above_limit_skipped(self):
        """文本弹幕完全越界（cy+height <= limit）时应被跳过。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=500.0, height=50, x=20)
        # cy + height = 550, limit = 600 → 完全越界

        renderer.render_frame([dm], [], layout, fade_out_zone=50.0)

        dm.render.assert_not_called()
        renderer.end()

    def test_text_at_threshold_edge_rendered(self):
        """文本弹幕恰好位于 threshold 边界时，应被渲染。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=650.0, height=50, x=20)
        # cy=650, threshold=650 → cy < threshold 为 False，走全不透明路径

        renderer.render_frame([dm], [], layout, fade_out_zone=50.0)

        dm.render.assert_called_once()
        renderer.end()

    def test_opacity_ramps_inside_fade_zone(self):
        """淡出区内透明度线性递减：cy=625、limit=600、zone=50 → alpha=0.5。"""
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=625.0, height=50, x=20)

        with _renderer(_layer_params(800, 600)) as renderer:
            with patch.object(renderer.painter, "setOpacity") as set_opacity:
                renderer.render_frame([dm], [], layout, fade_out_zone=50.0)

        assert set_opacity.call_args_list == [call(0.5)]

    def test_zero_fade_zone_keeps_text_opaque(self):
        """fade_out_zone=0 = 关闭淡出：部分越界的弹幕仍全不透明。

        这是回归用例 —— 修复前该输入会走 `(cy - limit) / 0` 直接抛
        ZeroDivisionError（配置层放行 0，用户按「淡出区高度 0」的字面语义
        填 0 就会在压制中途崩溃）。
        """
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=580.0, height=50, x=20)
        # cy=580 < limit=600，cy+height=630 > limit → 部分越界，会走 alpha 公式

        with _renderer(_layer_params(800, 600)) as renderer:
            with patch.object(renderer.painter, "setOpacity") as set_opacity:
                renderer.render_frame([dm], [], layout, fade_out_zone=0.0)

        dm.render.assert_called_once()
        assert set_opacity.call_args_list == [call(1.0)]

    def test_zero_fade_zone_still_skips_fully_out_of_bounds(self):
        """关闭淡出只影响透明度，不影响「完全越界即跳过」的裁剪。"""
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=500.0, height=50, x=20)
        # cy + height = 550 <= limit → 完全越界

        with _renderer(_layer_params(800, 600)) as renderer:
            renderer.render_frame([dm], [], layout, fade_out_zone=0.0)

        dm.render.assert_not_called()

    def test_negative_fade_zone_treated_as_disabled(self):
        """负数按 0 处理（配置层已拦，但 render_frame 是公开入口）。

        取材针对 zone<0 与 zone=0 的**唯一可观测差异**：若不做 clamp，
        threshold 会落到 text_top 之下，完全越界的弹幕反而漏过裁剪被画出来。
        """
        layout = _layout_params(text_top=600)
        partial = _make_stub_dm(current_y=580.0, height=50, x=20)  # 部分越界
        above = _make_stub_dm(current_y=550.0, height=50, x=20)  # 完全越界

        with _renderer(_layer_params(800, 600)) as renderer:
            with patch.object(renderer.painter, "setOpacity") as set_opacity:
                renderer.render_frame([partial, above], [], layout, fade_out_zone=-60.0)

        partial.render.assert_called_once()
        assert set_opacity.call_args_list == [call(1.0)]
        above.render.assert_not_called()

    def test_text_above_threshold_rendered(self):
        """文本弹幕在 threshold 以上时，应正常渲染。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        dm = _make_stub_dm(current_y=700.0, height=50, x=20)

        renderer.render_frame([dm], [], layout, fade_out_zone=50.0)

        dm.render.assert_called_once()
        renderer.end()

    def test_gift_always_rendered_in_fade_zone(self):
        """礼物弹幕即使在淡出区域内也应被渲染（不受淡出影响）。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        gift_dm = _make_stub_dm(current_y=620.0, height=50, x=20)

        renderer.render_frame([], [gift_dm], layout, fade_out_zone=50.0)

        gift_dm.render.assert_called_once()
        renderer.end()

    def test_gift_above_limit_still_rendered(self):
        """礼物弹幕即使完全越界也不应被跳过（礼物不受淡出限制）。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        layout = _layout_params(text_top=600)
        gift_dm = _make_stub_dm(current_y=500.0, height=50, x=20)

        renderer.render_frame([], [gift_dm], layout, fade_out_zone=50.0)

        gift_dm.render.assert_called_once()
        renderer.end()

    def test_multiple_text_danmaku(self):
        """多个文本弹幕应全部渲染。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        dm_list = [
            _make_stub_dm(current_y=800.0 - i * 60, height=50, x=20) for i in range(3)
        ]

        renderer.render_frame(dm_list, [], _layout_params(), fade_out_zone=50.0)

        for dm in dm_list:
            dm.render.assert_called_once()
        renderer.end()

    def test_local_coordinates_correct(self):
        """验证 local_x / local_y 计算正确。"""
        lp = _layer_params(layer_x=20, layer_y=100, layer_w=800, layer_h=600)
        renderer = DanmakuRenderer(lp)
        dm = _make_stub_dm(current_y=800.0, height=50, x=120)

        renderer.render_frame([dm], [], _layout_params(), fade_out_zone=50.0)

        dm.render.assert_called_once()
        args = dm.render.call_args[0]
        local_x = args[1]
        local_y = args[2]
        assert local_x == 100  # 120 - 20
        assert local_y == 700  # int(800) - 100
        renderer.end()

    def test_local_coordinates_with_layer_offset(self):
        """验证 layer_y 非零时 local_y 计算正确。"""
        lp = _layer_params(layer_x=0, layer_y=200, layer_w=800, layer_h=400)
        renderer = DanmakuRenderer(lp)
        dm = _make_stub_dm(current_y=800.0, height=50, x=0)

        renderer.render_frame([dm], [], _layout_params(), fade_out_zone=50.0)

        dm.render.assert_called_once()
        args = dm.render.call_args[0]
        local_y = args[2]
        assert local_y == 600  # int(800) - 200
        renderer.end()


# =============================================================================
# get_frame_data
# =============================================================================


class TestGetFrameData:
    """测试 get_frame_data：返回 memoryview 视图。"""

    def test_returns_memoryview(self):
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        data = renderer.get_frame_data()
        assert isinstance(data, memoryview)
        renderer.end()

    def test_data_has_correct_length(self):
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        data = renderer.get_frame_data()
        expected_len = 800 * 600 * 4  # ARGB32 = 4 bytes per pixel
        assert len(data) == expected_len
        renderer.end()


# =============================================================================
# end
# =============================================================================


class TestEnd:
    """测试 end()：资源释放。"""

    def test_end_stops_painter(self):
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        renderer.end()
        assert not renderer.painter.isActive()

    def test_double_end_no_error(self):
        """连续两次 end() 不应抛出异常。"""
        lp = _layer_params(800, 600)
        renderer = DanmakuRenderer(lp)
        renderer.end()
        renderer.end()
