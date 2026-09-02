"""测试弹幕文本渲染为图片

针对竖屏 1080x1920 视频，测试指定弹幕文本的渲染效果。
"""

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from danmakupro.config.models import DEFAULT_CONFIG
from danmakupro.input.event import DanmakuEvent
from danmakupro.layout.engine import LayoutEngine
from danmakupro.render.assets import AssetLoader
from danmakupro.render.layout_builder import DanmakuLayoutBuilder


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    cfg = DEFAULT_CONFIG

    # 1. 加载资源
    al = AssetLoader(
        font_size=cfg.style.font_size,
        assets_dir="assets",
    )
    print(f"字体族: {al.font.families()}")
    print(f"字体大小: {cfg.style.font_size}pt, 行高: {al.line_height}px")

    # 2. 构造 DanmakuEvent
    event = DanmakuEvent(
        time=29.788,
        user="阿支",
        text=(
            "让老肥游一下泳让老肥游一下泳让老肥游一下泳"
            "让老肥游一下泳让老肥游一下泳让老肥游一下泳"
            "让老肥游一下泳让"
        ),
    )
    print(f"\n弹幕事件: user={event.user}, time={event.time}s")
    print(f"文本长度: {len(event.text)} 字符")

    # 3. 计算布局参数 (1080x1920 竖屏)
    lp, layer = LayoutEngine.calculate_params(
        1080, 1920,
        style=cfg.style, ratio=cfg.ratio,
        line_height=al.line_height,
    )
    print(f"\n视频分辨率: 1080x1920")
    print(f"文本弹幕最大宽度: {lp.text_w}px")
    print(f"弹幕区: bottom={lp.bottom}, top={lp.text_top}, height={lp.text_h}")
    print(f"渲染层: {layer.layer_w}x{layer.layer_h}, xy=({layer.layer_x},{layer.layer_y})")

    # 4. 构建布局
    builder = DanmakuLayoutBuilder(
        fm=al.fm, emoji_cache=al.emoji_cache, gift_cache=al.gift_cache,
        max_content_width=lp.text_w, line_height=al.line_height, style=cfg.style,
    )
    layout = builder.build(event)

    print(f"\n--- 布局结果 ---")
    print(f"折行数: {len(layout.rows)} 行")
    print(f"气泡总宽度: {layout.total_width}px")
    print(f"气泡总高度: {layout.height}px")
    print(f"圆角半径: {layout.radius}")
    for i, row in enumerate(layout.rows):
        segs = []
        for seg in row.segments:
            segs.append(f"[{seg.type}]{seg.content!r}({seg.width}px)")
        print(f"  第{i}行 ({row.width}px): {' | '.join(segs)}")

    # 5. 预渲染
    layout.pre_render(al.font, al.emoji_cache, al.gift_cache, al.bg_color)
    assert layout.cached_image is not None
    print(f"\n预渲染图片尺寸: {layout.cached_image.width()}x{layout.cached_image.height()}")

    # 6. 保存
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "danmaku_test.png"
    layout.cached_image.save(str(output_path))
    print(f"\n已保存到: {output_path.resolve()}")
    print("完成!")


if __name__ == "__main__":
    main()