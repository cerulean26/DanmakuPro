"""命令行入口模块

用法: danmakupro video.mp4 danmaku.xml
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

try:
    from .burner import DanmakuBurner   # 包内执行 → 成功
except ImportError:
    from danmakupro.burner import DanmakuBurner # 脚本执行 → 回退
    
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

def _configure_logger() -> None:
    """配置 loguru 日志：stderr 输出 INFO 级别，文件输出 DEBUG 级别。"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time} | {level} | {message}")
    logger.add(
        str(_LOG_DIR / "ffmpeg.log"), level="DEBUG", rotation="100 MB",
        format="{time} | {level} | {message}",
    )


def main() -> None:
    """主入口函数：解析命令行参数，启动压制引擎"""
    _configure_logger()

    parser = argparse.ArgumentParser(
        prog="danmakupro",
        description="抖音直播弹幕压制工具 - 将 XML 弹幕渲染叠加到视频",
    )
    parser.add_argument(
        "video",
        help="视频文件路径",
    )
    parser.add_argument(
        "xml",
        help="弹幕 XML 文件路径",
    )
    args = parser.parse_args()

    logger.info(f"开始处理视频: {args.video}...")
    burner = DanmakuBurner(video_in=args.video, xml_in=args.xml)
    burner.run()