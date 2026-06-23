"""弹幕压制核心引擎模块

DanmakuBurner 是弹幕压制的编排器，负责组合各子模块完成完整的处理管线：
    1. 解析 XML 弹幕数据
    2. 加载资源（Emoji、礼物图片、字体）
    3. 获取视频元数据
    4. 计算布局参数
    5. 预创建弹幕对象
    6. 启动 FFmpeg 进程
    7. 主渲染循环（逐帧生成弹幕、更新位置、碰撞检测、渲染、写入管道）
    8. 资源清理与报告生成

子模块：
    - AssetLoader:    资源加载（字体、Emoji、礼物图片）
    - LayoutEngine:   布局计算、弹幕生成、位置更新、碰撞检测
    - FFmpegManager:  FFmpeg 命令构建、进程管理、管道写入
    - DanmakuRenderer: 画布管理、帧渲染

技术栈：
    - 视频解码/编码：FFmpeg + CUDA (NVENC/NVDEC)
    - 弹幕渲染：PySide6 (Qt) + QPainter
"""

from pathlib import Path

from loguru import logger
from tqdm import tqdm

from .config import H264_ALIGNMENT, FADE_OUT_ZONE, GIFT_FADE_OUT_ZONE, GIFT_DAMPING_FACTOR, GIFT_DWELL_TIME
from .models import ActiveDanmaku
from .parser import parse_xml
from .asset_loader import AssetLoader
from .layout_engine import LayoutEngine
from .layout_params import LayoutParams, LayerParams
from .ffmpeg_manager import FFmpegManager
from .renderer import DanmakuRenderer


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class DanmakuBurner:
    """弹幕压制引擎：将 XML 弹幕渲染并叠加到视频上。

    使用方式:
        >>> burner = DanmakuBurner(video_in="input.mp4", xml_in="danmaku.xml")
        >>> burner.run()
    """

    def __init__(self, video_in: str, xml_in: str):
        """初始化压制引擎。

        Args:
            video_in: 输入视频文件路径
            xml_in: 输入弹幕 XML 文件路径
        """
        self.video_in = video_in
        self.xml_in = xml_in

        video_path = Path(video_in)
        self.video_out = str(video_path.parent / f"{video_path.stem}-弹幕版.mp4")

        self._asset_loader = AssetLoader()
        self._layout_engine = LayoutEngine(self._asset_loader)
        self._ffmpeg_manager = FFmpegManager(video_in, self.video_out)

    def _render_loop(
        self,
        fps: float,
        total_frames: int,
        danmaku_pool: list[ActiveDanmaku],
        layout_params: LayoutParams,
        layer_params: LayerParams,
        renderer: DanmakuRenderer,
    ) -> None:
        """主渲染循环：逐帧处理视频。

        每帧执行以下步骤：
            1. 生成当前时间点的新弹幕
            2. 更新所有弹幕位置（含平滑动效）
            3. 回收超出屏幕的弹幕（释放缓存图片内存）
            4. 碰撞检测与推挤
            5. 渲染弹幕到画布
            6. 写入 FFmpeg 管道

        Args:
            fps: 视频帧率
            total_frames: 总帧数
            danmaku_pool: 预创建的弹幕池
            layout_params: 布局参数
            layer_params: 渲染层参数
            renderer: 弹幕渲染器
        """
        loader = self._asset_loader
        ffmpeg = self._ffmpeg_manager

        active_danmakus: list[ActiveDanmaku] = []
        event_idx = 0

        text_fade_out_zone, text_fade_out_threshold = LayoutEngine.get_fade_out_params(
            layout_params.max_y_limit, FADE_OUT_ZONE,
        )
        gift_fade_out_zone, gift_fade_out_threshold = LayoutEngine.get_fade_out_params(
            layout_params.gift_y_limit, GIFT_FADE_OUT_ZONE,
        )

        for frame_idx in tqdm(range(total_frames), desc="视频压制进度", unit="帧"):
            current_time = frame_idx / fps

            event_idx, is_any_new_spawned = LayoutEngine.spawn_new_danmakus(
                current_time, danmaku_pool, active_danmakus, event_idx,
                loader.font, loader.emoji_cache, loader.gift_cache, loader.bg_color,
            )

            # 拆分文本弹幕和礼物弹幕
            text_danmakus: list[ActiveDanmaku] = []
            gift_danmakus: list[ActiveDanmaku] = []
            text_has_new = False
            gift_has_new = False
            for dm in active_danmakus:
                if dm.event.is_gift:
                    gift_danmakus.append(dm)
                    if is_any_new_spawned:
                        gift_has_new = True
                else:
                    text_danmakus.append(dm)
                    if is_any_new_spawned:
                        text_has_new = True

            # 文本区：从 container_bottom 到 max_y_limit
            LayoutEngine.update_positions(
                text_danmakus, text_has_new,
                layout_params.container_bottom, layout_params.bubble_vertical_gap,
            )
            LayoutEngine.recycle_out_of_bounds(text_danmakus, layout_params.max_y_limit)
            LayoutEngine.handle_collisions(
                text_danmakus, layout_params.max_y_limit, layout_params.bubble_vertical_gap,
            )

            # 礼物区：从 max_y_limit 到 gift_y_limit
            LayoutEngine.update_positions(
                gift_danmakus, gift_has_new,
                layout_params.max_y_limit, layout_params.bubble_vertical_gap,
                GIFT_DAMPING_FACTOR,
            )
            LayoutEngine.recycle_out_of_bounds(gift_danmakus, layout_params.gift_y_limit, current_time, GIFT_DWELL_TIME)
            LayoutEngine.handle_collisions(
                gift_danmakus, layout_params.gift_y_limit, layout_params.bubble_vertical_gap,
            )

            # 合并回活跃列表（供下一帧 spawn 使用）
            active_danmakus = text_danmakus + gift_danmakus

            renderer.render_frame(
                text_danmakus, gift_danmakus,
                layer_params, layout_params,
                text_fade_out_zone, text_fade_out_threshold,
                gift_fade_out_zone, gift_fade_out_threshold,
            )

            ffmpeg.write_frame(renderer.get_frame_data())

    def run(self) -> None:
        """主执行流程：完整压制管线。

        步骤:
            1. 解析 XML 弹幕数据
            2. 加载资源（Emoji、礼物图片）
            3. 获取视频元数据（尺寸、帧率、帧数）
            4. 预创建弹幕对象
            5. 启动 FFmpeg 进程
            6. 主渲染循环
            7. 资源清理与报告生成
        """
        events = parse_xml(self.xml_in)

        self._asset_loader.load_assets(events)

        v_info = self._ffmpeg_manager.get_video_info()
        raw_w: int = int(v_info['w'])
        raw_h: int = int(v_info['h'])
        fps: float = float(v_info['fps'])
        total_frames: int = int(v_info['frames'])

        w = int(((raw_w + H264_ALIGNMENT - 1) // H264_ALIGNMENT) * H264_ALIGNMENT)
        h = int(((raw_h + H264_ALIGNMENT - 1) // H264_ALIGNMENT) * H264_ALIGNMENT)

        layout_params, layer_params = LayoutEngine.calculate_params(w, h)
        danmaku_pool = self._layout_engine.preload_danmaku_objects(events, layout_params)

        logger.info("[5/5] 准备启动视频压制进程...")
        ffmpeg_cmd = self._ffmpeg_manager.build_command(fps, w, h, layer_params)

        renderer: DanmakuRenderer | None = None

        try:
            self._ffmpeg_manager.start(ffmpeg_cmd)

            renderer = DanmakuRenderer(layer_params)

            self._render_loop(
                fps, total_frames, danmaku_pool,
                layout_params, layer_params,
                renderer,
            )

        except KeyboardInterrupt:
            logger.warning("用户中断压制")
        except Exception:
            logger.exception("压制过程中出现未预料的错误")
            raise
        finally:
            if renderer is not None:
                renderer.end()
            self._ffmpeg_manager.cleanup()