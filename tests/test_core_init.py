"""core 模块导出测试"""

from danmakupro.core import DanmakuBurner, RenderPipeline, PipelineResult


def test_exports():
    assert DanmakuBurner is not None
    assert RenderPipeline is not None
    assert PipelineResult is not None