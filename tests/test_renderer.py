"""renderer.py 单元测试

测试 DanmakuRenderer 的初始化、帧渲染（含淡出）、帧数据获取和资源释放。

注意：渲染器使用真实的 QPainter，因此不直接验证 setOpacity 的调用参数。
淡出逻辑通过 render 方法是否被调用来间接验证。
"""

from unittest.mock import MagicMock

from PySide6.QtGui import QImage

from danmakupro.render.renderer import DanmakuRenderer
from danmakupro.layout.params import LayoutParams, LayerParams


# =============================================================================
# 测试辅助
# =============================================================================

def _layer_params(
    layer_w: int = 800, layer_h: int = 600,
    layer_x: int = 20, layer_y: int = 0,
) -> LayerParams:
    return LayerParams(
        layer_x=layer_x, layer_y=layer_y,
        layer_w=layer_w, layer_h=layer_h,
    )


def _layout_params(
    bottom: int = 1000, text_h: int = 400, text_top: int = 600,
    text_w: int = 800, gap: int = 4,
    gift_top: int = 400, gift_h: int = 200,
) -> LayoutParams:
    return LayoutParams(
        bottom=bottom, text_h=text_h, text_top=text_top,
        text_w=text_w, gap=gap,
        gift_top=gift_top, gift_h=gift_h,
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

        renderer.render_frame([text_dm], [gift_dm], _layout_params(), fade_out_zone=50.0)

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
        dm_list = [_make_stub_dm(current_y=800.0 - i * 60, height=50, x=20) for i in range(3)]

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