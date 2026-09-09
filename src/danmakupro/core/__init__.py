"""核心模块

包含主流程编排和渲染管线。
"""

from .burner import DanmakuBurner
from .pipeline import RenderPipeline, PipelineResult

__all__ = ["DanmakuBurner", "RenderPipeline", "PipelineResult"]