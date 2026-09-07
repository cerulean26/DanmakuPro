"""命令行入口模块

用法: danmakupro video.mp4 danmaku.xml 
     danmakupro source/5.flv source/5.xml --encode gpu --config ./danmakupro.yaml -f
"""

from __future__ import annotations

import os
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.qpa.fonts=false;qt.text.font.db=false",
)

import argparse

from loguru import logger
from PySide6.QtWidgets import QApplication

from .core.burner import DanmakuBurner
from .config.models import EncodeMode
from .config.loader import load_config
from .errors import DanmakuProError, handle_error
from .logger_config import configure_logger
from .utils.helpers import ensure_qt_app


def main() -> None:
    """主入口函数"""
    parser = argparse.ArgumentParser(
        prog="danmakupro",
        description="抖音直播弹幕压制工具",
    )
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("xml", help="弹幕 XML 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出视频路径")
    parser.add_argument(
        "--encode",
        choices=[EncodeMode.AUTO, EncodeMode.GPU, EncodeMode.QSV, EncodeMode.CPU],
        default=EncodeMode.AUTO,
        help="编码模式",
    )
    parser.add_argument("-c", "--config", default=None, help="配置文件路径")
    parser.add_argument(
        "-f", "--force", action="store_true", default=False,
        help="强制覆盖已存在的输出文件",
    )
    args = parser.parse_args()
    configure_logger()
    ensure_qt_app()
    config = load_config(args.config)
    # 捕获创建Burner时的异常，避免程序崩溃
    try:
        burner = DanmakuBurner(
            video_in=args.video, xml_in=args.xml,
            video_out=args.output, encode_mode=args.encode,
            config=config, force=args.force,
        )
    except DanmakuProError as e:
        logger.error(f"[{e.category.value}] {e}")
        raise SystemExit(1)
    except Exception as e:
        handle_error(e, component="cli", operation="create_burner")
        raise SystemExit(1)
    # 捕获处理Burner时的异常，避免程序崩溃
    try:
        burner.run()
    except DanmakuProError as e:
        logger.error(f"压制失败 [{e.category.value}]: {e}")
        raise SystemExit(1)
    except Exception as e:
        handle_error(e, component="cli", operation="run")
        raise SystemExit(1)
    finally:
        app = QApplication.instance()
        if app is not None:
            app.quit()
            app.deleteLater()


if __name__ == "__main__":
    main()