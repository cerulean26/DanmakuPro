"""渲染管线

RenderPipeline 封装弹幕渲染主循环，负责逐帧生成、布局更新、渲染和编码。
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import TYPE_CHECKING

from loguru import logger
from tqdm import tqdm

from ..config.models import DanmakuConfig
from ..errors import EncodeError
from ..layout.engine import LayoutEngine, LayoutContext
from ..layout.params import LayoutParams, LayerParams
from ..render.renderer import DanmakuRenderer

if TYPE_CHECKING:
    from ..input.event import DanmakuEvent
    from ..render.assets import AssetLoader
    from ..render.layout_builder import DanmakuLayoutBuilder
    from ..encode.ffmpeg import FFmpegManager
    from ..render.active_view import ActiveDanmakuView


@dataclass
class PipelineResult:
    """渲染管线执行结果"""
    text_spawned: int
    gift_spawned: int
    layout_ctx: LayoutContext
    t_start: float
    total_text_danmaku: int
    total_gift_danmaku: int


class RenderPipeline:
    """渲染管线：逐帧生成、布局更新、渲染和编码。

    封装 _render_loop 及其子方法 _encode_frame，
    将渲染主循环从 DanmakuBurner 中分离出来。
    """

    def __init__(
        self,
        frame_encoder: FFmpegManager,
        config: DanmakuConfig,
        asset_provider: AssetLoader,
    ) -> None:
        self._frame_encoder = frame_encoder
        self._config = config
        self._asset_provider = asset_provider

    def run(
        self,
        fps: float,
        total_frames: int,
        events: list[DanmakuEvent],
        layout_builder: DanmakuLayoutBuilder,
        layout_params: LayoutParams,
        layer_params: LayerParams,
    ) -> PipelineResult:
        """执行渲染主循环。

        Args:
            fps: 视频帧率
            total_frames: 总帧数
            events: 弹幕事件列表
            layout_builder: 弹幕布局构建器
            layout_params: 布局参数
            layer_params: 层参数

        Returns:
            PipelineResult: 包含发射统计、布局上下文和耗时信息

        Raises:
            DanmakuProError: 弹幕压制过程中发生错误
        """
        anim = self._config.animation

        active_text: list[ActiveDanmakuView] = []
        active_gift: list[ActiveDanmakuView] = []

        layout_ctx = LayoutContext(animation=anim)

        renderer = DanmakuRenderer(layer_params)

        total_text_danmaku = sum(1 for e in events if not e.is_gift)
        total_gift_danmaku = len(events) - total_text_danmaku

        logger.complete()

        pbar = tqdm(
            total=total_frames, desc="压制进度", unit="帧",
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}{postfix}]",
        )

        SPEED_UPDATE_INTERVAL = 30
        fade_out_zone = self._config.style.fade_out_zone
        total_text_spawned = 0
        total_gift_spawned = 0

        t_start = time.perf_counter()
        try:
            for frame_idx in range(total_frames):
                current_time = frame_idx / fps

                text_has_new, gift_has_new, text_emitted, gift_emitted = (
                    LayoutEngine.spawn_new_danmakus(
                        layout_ctx, current_time, events, active_text, active_gift,
                        layout_builder, self._asset_provider, self._config.style,
                    )
                )
                total_text_spawned += text_emitted
                total_gift_spawned += gift_emitted

                LayoutEngine.update_danmaku_layer(
                    active_text, text_has_new,
                    layout_params.bottom, layout_params.text_top,
                    layout_params.gap, anim.text_damping_factor,
                )
                LayoutEngine.update_danmaku_layer(
                    active_gift, gift_has_new,
                    layout_params.text_top, layout_params.gift_top,
                    layout_params.gap, anim.gift_damping_factor,
                    current_time, anim.gift_dwell_time,
                )

                renderer.render_frame(
                    active_text, active_gift,
                    layout_params,
                    fade_out_zone,
                )

                self._encode_frame(
                    renderer, pbar, frame_idx, total_frames,
                )

                if frame_idx % SPEED_UPDATE_INTERVAL == 0:
                    speed = self._frame_encoder.current_speed
                    pbar.set_postfix(
                        {"speed": f"{speed:.1f}x" if speed > 0 else "--"}
                    )
        finally:
            renderer.end()
            pbar.close()

        return PipelineResult(
            text_spawned=total_text_spawned,
            gift_spawned=total_gift_spawned,
            layout_ctx=layout_ctx,
            t_start=t_start,
            total_text_danmaku=total_text_danmaku,
            total_gift_danmaku=total_gift_danmaku,
        )

    def _encode_frame(
        self,
        renderer: DanmakuRenderer,
        pbar: tqdm,
        frame_idx: int,
        total_frames: int,
    ) -> None:
        """提交单帧编码，处理编码错误。

        Args:
            renderer: 渲染器
            pbar: 进度条
            frame_idx: 当前帧索引
            total_frames: 总帧数

        Raises:
            EncodeError: 编码器错误且策略为中止
        """
        try:
            self._frame_encoder.submit_frame(renderer.get_frame_data())
            pbar.update(1)
        except (BrokenPipeError, OSError, RuntimeError) as e:
            raise EncodeError(f"编码器错误 [帧 {frame_idx}]: {e}") from e