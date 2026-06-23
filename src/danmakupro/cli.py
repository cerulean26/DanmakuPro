"""命令行入口模块

用法: danmakupro video.mp4 danmaku.xml
"""

import argparse

from loguru import logger

from .burner import DanmakuBurner
from .logger_config import configure_logger


def main() -> None:
    """主入口函数：解析命令行参数，启动压制引擎"""
    configure_logger()

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