"""命令行入口模块

用法: danmakupro video.mp4 danmaku.xml
     danmakupro source/5.flv source/5.xml --encode gpu --config ./danmakupro.yaml -f
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

#: 用户中断（Ctrl+C）的退出码：128 + SIGINT(2)，沿用 POSIX 约定。
#: 不让它向上抛到解释器 —— 那样 Windows 上会得到 STATUS_CONTROL_C_EXIT
#: (0xC000013A / 3221225786)，POSIX 上又是另一个数，调用方难以判断。
EXIT_INTERRUPTED = 130

#: 随包分发的配置模板，`danmakupro --init-config` 的来源。
EXAMPLE_CONFIG = Path(__file__).resolve().parent / "danmakupro.example.yaml"


def init_config(dest: str | None = None, force: bool = False) -> int:
    """把随包配置模板写到用户指定位置。

    配置是用户私有产物：模板本身不会被自动加载，只有用户主动生成/复制成
    `danmakupro.yaml` 后才生效。这样既保留了「不改配置也能跑」的默认体验，
    又不会让某台机器上的临时调参混进版本库。

    Args:
        dest: 目标路径，默认当前目录下的 danmakupro.yaml
        force: 目标已存在时是否覆盖

    Returns:
        进程退出码（0 成功，1 失败）
    """
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
        choices=[EncodeMode.AUTO, EncodeMode.GPU, EncodeMode.QSV, EncodeMode.CPU],
        default=EncodeMode.AUTO,
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
        help="强制覆盖已存在的输出文件（配合 --init-config 时为覆盖已有配置）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="仅检查资源完整性，不执行压制（字体/图片覆盖率、视频信息）",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        default=False,
        help="在当前目录生成配置模板 danmakupro.yaml 后退出",
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
    config = load_config(args.config)
    # 捕获创建Burner时的异常，避免程序崩溃
    try:
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
        handle_error(e, component="cli", operation="create_burner")
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
