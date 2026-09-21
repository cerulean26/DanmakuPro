"""命令行入口模块

用法: danmakupro video.mp4 danmaku.xml
     danmakupro source/5.flv source/5.xml --encode h264_nvenc -c ./danmakupro.yaml -f
     danmakupro video.mp4 danmaku.xml --check
     danmakupro --init-config

`--encode` 的合法取值即 EncodeMode 的字面量（9 个：h264 / h264_nvenc / h264_qsv / h265 /
h265_nvenc / h265_qsv / av1 / av1_nvenc / av1_qsv），其余取值由 argparse 以退出码 2 拒绝。
完整说明见 docs/configuration.md。
"""

from __future__ import annotations

import os
import argparse
from pathlib import Path

from loguru import logger
from PySide6.QtWidgets import QApplication

from .core.burner import DanmakuBurner
from .config.models import EncodeMode
from .config.loader import load_config
from .errors import DanmakuProError, handle_error
from .logger_config import configure_logger
from .utils.helpers import ensure_qt_app

#: Ctrl+C 的统一退出码（130 = 128 + SIGINT），屏蔽平台差异。
EXIT_INTERRUPTED = 130

#: 随包分发的配置模板，`danmakupro --init-config` 的来源。
EXAMPLE_CONFIG = Path(__file__).resolve().parent / "danmakupro.example.yaml"


def init_config(dest: str | None = None, force: bool = False) -> int:
    """将随包配置模板写到用户指定位置，已存在时不覆盖（除非 -f）。"""
    target = Path(dest) if dest else Path("danmakupro.yaml")
    if target.exists() and not force:
        logger.error("{} 已存在，若确认覆盖请加 -f", target)
        return 1
    try:
        target.write_text(EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError as e:
        logger.error("生成配置模板失败: {} - {}", target, e)
        return 1
    logger.info("已生成配置模板: {}", target.resolve())
    logger.info(
        "按需修改后重新运行即可生效（当前目录下的 danmakupro.yaml 会被自动加载）"
    )
    return 0


def main() -> None:
    """主入口函数"""
    os.environ.setdefault(
        "QT_LOGGING_RULES",
        "qt.qpa.fonts=false;qt.text.font.db=false",
    )

    parser = argparse.ArgumentParser(
        prog="danmakupro",
        description="抖音直播弹幕压制工具",
    )
    # video/xml 声明为可选，是为了让 `--init-config` 能在没有素材时单独运行；
    # 常规流程的必填性在下面手动补回（退出码 2，与 argparse 缺参一致）。
    parser.add_argument("video", nargs="?", help="视频文件路径")
    parser.add_argument("xml", nargs="?", help="弹幕 XML 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出视频路径")
    parser.add_argument(
        "--encode",
        choices=[e.value for e in EncodeMode],
        default=EncodeMode.H264.value,
        help="编码模式",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="配置文件路径（配合 --init-config 时表示模板生成路径）",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        default=False,
        help="输出文件已存在时跳过询问直接覆盖（配合 --init-config 时为覆盖已有配置）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="仅检查不压制（视频信息、弹幕统计、资源覆盖率、发射能力与编码器）",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        default=False,
        help="生成配置模板后退出（默认 ./danmakupro.yaml，-c 可指定路径）",
    )
    args = parser.parse_args()
    configure_logger()

    if args.init_config:
        raise SystemExit(init_config(args.config, args.force))

    if not args.video or not args.xml:
        parser.error(
            "需要同时提供 video 与 xml 参数（或用 --init-config 生成配置模板）"
        )

    ensure_qt_app()
    try:
        config = load_config(args.config)
        burner = DanmakuBurner(
            video_in=args.video,
            xml_in=args.xml,
            video_out=args.output,
            encode_mode=args.encode,
            config=config,
            force=args.force,
            check_only=args.check,
        )
    except DanmakuProError as e:
        logger.error(f"[{e.category.value}] {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        logger.warning("已取消")
        raise SystemExit(EXIT_INTERRUPTED)
    except Exception as e:
        handle_error(e, component="cli", operation="startup")
        raise SystemExit(1)

    # 捕获处理Burner时的异常，避免程序崩溃
    try:
        if args.check:
            burner.check()
        else:
            burner.run()
    except KeyboardInterrupt:
        # KeyboardInterrupt 继承自 BaseException，上面的 except Exception
        # 抓不到，必须单独处理，否则会以平台相关的状态码退出。
        logger.warning("已取消，未生成完整输出文件")
        raise SystemExit(EXIT_INTERRUPTED)
    except DanmakuProError as e:
        action = "资源检查" if args.check else "压制"
        logger.error(f"{action}失败 [{e.category.value}]: {e}")
        raise SystemExit(1)
    except Exception as e:
        action = "check" if args.check else "run"
        handle_error(e, component="cli", operation=action)
        raise SystemExit(1)
    finally:
        app = QApplication.instance()
        if app is not None:
            app.quit()
            app.deleteLater()


if __name__ == "__main__":
    main()
