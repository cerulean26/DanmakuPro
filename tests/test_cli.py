"""CLI 入口单元测试"""

import contextlib
import runpy
import sys
import warnings
from unittest.mock import patch, MagicMock

import pytest

from danmakupro.cli import EXAMPLE_CONFIG, EXIT_INTERRUPTED, init_config, main
from danmakupro.config.models import EncodeMode
from danmakupro.errors import DanmakuProError, ErrorCategory


@contextlib.contextmanager
def _patched_cli(*argv):
    """把 main() 的外部依赖整体换成替身，避免每条用例重复六层 with。

    Yields:
        (DanmakuBurner 的 mock 类, QApplication 的 mock 类)
    """
    with (
        patch("sys.argv", ["danmakupro", *argv]),
        patch("danmakupro.cli.load_config"),
        patch("danmakupro.cli.configure_logger"),
        patch("danmakupro.cli.ensure_qt_app"),
        patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
        patch("danmakupro.cli.QApplication") as mock_qapp,
    ):
        yield mock_burner_cls, mock_qapp


class TestCLIMain:
    def test_help_exits(self):
        with patch("sys.argv", ["danmakupro", "--help"]):
            with pytest.raises(SystemExit):
                main()

    def test_missing_args_exits(self):
        with patch("sys.argv", ["danmakupro"]):
            with pytest.raises(SystemExit):
                main()

    def test_basic_arguments(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml)]),
            patch("danmakupro.cli.load_config") as mock_load_config,
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            mock_burner_cls.assert_called_once()
            mock_burner.run.assert_called_once()

    def test_force_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml), "-f"]),
            patch("danmakupro.cli.load_config") as mock_load_config,
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["force"] is True

    def test_encode_mode(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml), "--encode", "h264"]),
            patch("danmakupro.cli.load_config") as mock_load_config,
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["encode_mode"] == EncodeMode.H264.value

    def test_output_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        out = tmp_path / "out.mp4"
        out.touch()

        with (
            patch(
                "sys.argv", ["danmakupro", str(video), str(xml), "-o", str(out), "-f"]
            ),
            patch("danmakupro.cli.load_config") as mock_load_config,
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            call_kwargs = mock_burner_cls.call_args[1]
            assert call_kwargs["video_out"] == str(out)

    def test_config_flag(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()
        cfg = tmp_path / "config.yaml"
        cfg.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml), "-c", str(cfg)]),
            patch("danmakupro.cli.load_config") as mock_load_config,
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner_cls.return_value = mock_burner
            mock_load_config.return_value = MagicMock()

            main()
            mock_load_config.assert_called_once_with(str(cfg))

    def test_burner_error_handling(self, tmp_path):
        from danmakupro.errors import DanmakuProError, ErrorCategory

        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml)]),
            patch("danmakupro.cli.load_config"),
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner_cls.side_effect = DanmakuProError(
                "test error",
                ErrorCategory.INPUT,
            )
            with pytest.raises(SystemExit):
                main()

    def test_interrupt_exit_code(self, tmp_path):
        """Ctrl+C 必须以明确的非 0 码退出，不能是 0（会被误判为成功）。"""
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml)]),
            patch("danmakupro.cli.load_config"),
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner.run.side_effect = KeyboardInterrupt
            mock_burner_cls.return_value = mock_burner
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 130

    def test_run_error_handling(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.touch()
        xml = tmp_path / "test.xml"
        xml.touch()

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml)]),
            patch("danmakupro.cli.load_config"),
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner") as mock_burner_cls,
            patch("danmakupro.cli.QApplication"),
        ):
            mock_burner = MagicMock()
            mock_burner.run.side_effect = RuntimeError("boom")
            mock_burner_cls.return_value = mock_burner
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1


class TestCLIErrorPaths:
    """CLI 的每个失败出口都要有确定的退出码与可读日志，不能静默通过。"""

    def test_interrupt_while_creating_burner(self):
        """构造 burner 阶段被 Ctrl+C：同样要 exit 130。

        这一支必须单独接住 —— KeyboardInterrupt 继承 BaseException，会穿透
        所有 `except Exception`，最终以平台相关状态码退出（Windows 上是
        0xC000013A / 3221225786），调用方无法统一判断。
        """
        with _patched_cli("v.mp4", "d.xml") as (mock_cls, _):
            mock_cls.side_effect = KeyboardInterrupt
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == EXIT_INTERRUPTED

    def test_unexpected_error_while_creating_burner(self):
        """构造阶段抛非 DanmakuProError：交给 handle_error 兜底，exit 1。"""
        with _patched_cli("v.mp4", "d.xml") as (mock_cls, _):
            mock_cls.side_effect = RuntimeError("boom")
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_bad_yaml_reports_config_error(self, tmp_path):
        """坏 YAML 必须 exit 1 + 单行 `[config]` 日志，不能吐栈回溯。

        其余用例都把 load_config 换成了替身，覆盖不到真实解析路径 ——
        load_config 曾位于 try 之外，`-c bad.yaml` 会把 ParserError 直接
        抛给用户。
        """
        video = tmp_path / "v.mp4"
        video.touch()
        xml = tmp_path / "d.xml"
        xml.touch()
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : :\n", encoding="utf-8")

        with (
            patch("sys.argv", ["danmakupro", str(video), str(xml), "-c", str(bad)]),
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app"),
            patch("danmakupro.cli.DanmakuBurner"),
            patch("danmakupro.cli.QApplication"),
            patch("danmakupro.cli.logger") as mock_logger,
        ):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        msg = mock_logger.error.call_args[0][0]
        assert "[config]" in msg
        assert "配置文件解析失败" in msg

    def test_check_flag_only_checks(self):
        """--check 只做资源检查，绝不能真的压制。"""
        with _patched_cli("v.mp4", "d.xml", "--check") as (mock_cls, _):
            burner = MagicMock()
            mock_cls.return_value = burner
            main()
        assert mock_cls.call_args.kwargs["check_only"] is True
        burner.check.assert_called_once()
        burner.run.assert_not_called()

    def test_danmakupro_error_while_running(self):
        """运行阶段抛 DanmakuProError：exit 1，日志写明是「压制」失败。"""
        with _patched_cli("v.mp4", "d.xml") as (mock_cls, _):
            burner = MagicMock()
            burner.run.side_effect = DanmakuProError("坏输入", ErrorCategory.INPUT)
            mock_cls.return_value = burner
            with patch("danmakupro.cli.logger") as mock_logger:
                with pytest.raises(SystemExit) as exc:
                    main()
            msg = mock_logger.error.call_args[0][0]
        assert exc.value.code == 1
        assert "压制失败" in msg
        assert "[input]" in msg

    def test_danmakupro_error_while_checking_says_resource_check(self):
        """同一个 except 分支里，--check 的动作词必须是「资源检查」。

        写死成「压制」会让只做检查的用户看到误导性报错。
        """
        with _patched_cli("v.mp4", "d.xml", "--check") as (mock_cls, _):
            burner = MagicMock()
            burner.check.side_effect = DanmakuProError(
                "缺素材",
                ErrorCategory.RESOURCE,
            )
            mock_cls.return_value = burner
            with patch("danmakupro.cli.logger") as mock_logger:
                with pytest.raises(SystemExit):
                    main()
            msg = mock_logger.error.call_args[0][0]
        assert "资源检查失败" in msg
        assert "压制" not in msg

    def test_application_is_released_even_on_error(self):
        """finally 里必须释放 QApplication，否则 GUI 复用场景会残留实例。"""
        with _patched_cli("v.mp4", "d.xml") as (mock_cls, mock_qapp):
            burner = MagicMock()
            burner.run.side_effect = RuntimeError("boom")
            mock_cls.return_value = burner
            with pytest.raises(SystemExit):
                main()
        mock_qapp.instance.return_value.quit.assert_called_once()
        mock_qapp.instance.return_value.deleteLater.assert_called_once()


class TestModuleEntrypoint:
    """`python -m danmakupro.cli` 这条路必须真的进 main()。"""

    def test_module_invocation_reaches_main(self, monkeypatch):
        """__main__ 守卫无法被普通 import 覆盖：模块已在 sys.modules 中，
        重导入不会再次执行顶层代码。用 runpy 以 __main__ 名义重新执行整个
        模块；用 --help 让它在 argparse 处退出，不触碰任何真实文件。
        """
        monkeypatch.setattr(sys, "argv", ["danmakupro", "--help"])
        with warnings.catch_warnings():
            # runpy 会告警「模块已在 sys.modules 中却又以 __main__ 执行」。
            # 这里是有意为之：本模块没有模块级可变状态（只有一个
            # EXIT_INTERRUPTED 常量），第二份副本不会产生副作用。换成子进程
            # 跑 `python -m` 确实更贴近真实用法，但子进程不会进覆盖率统计，
            # 就失去了这条用例的意义。
            warnings.simplefilter("ignore", RuntimeWarning)
            with pytest.raises(SystemExit) as exc:
                runpy.run_module("danmakupro.cli", run_name="__main__")
        assert exc.value.code == 0


class TestInitConfig:
    """`--init-config`：把随包模板交给用户，是自定义配置的入口。

    配置属用户私有产物，模板本身不参与自动加载 —— 因此这条路径必须能在
    没有素材、没有 Qt 的情况下独立跑通。
    """

    def _run(self, *argv):
        """在给定 argv 下跑 main()，返回 SystemExit 的退出码。"""
        with (
            patch("sys.argv", ["danmakupro", *argv]),
            patch("danmakupro.cli.configure_logger"),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        return exc.value.code

    def test_writes_packaged_template_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        code = self._run("--init-config")
        assert code == 0
        target = tmp_path / "danmakupro.yaml"
        assert target.exists()
        # 生成的内容必须就是随包模板，而不是另写一份
        assert target.read_text(encoding="utf-8") == EXAMPLE_CONFIG.read_text(
            encoding="utf-8"
        )

    def test_does_not_start_qt(self, tmp_path, monkeypatch):
        """纯文件操作，不应拉起 QApplication。"""
        monkeypatch.chdir(tmp_path)
        with (
            patch("sys.argv", ["danmakupro", "--init-config"]),
            patch("danmakupro.cli.configure_logger"),
            patch("danmakupro.cli.ensure_qt_app") as mock_qt,
        ):
            with pytest.raises(SystemExit):
                main()
        mock_qt.assert_not_called()

    def test_refuses_overwrite_without_force(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "danmakupro.yaml"
        target.write_text("style:\n  font_size: 99\n", encoding="utf-8")
        assert self._run("--init-config") == 1
        assert "font_size: 99" in target.read_text(encoding="utf-8")

    def test_force_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "danmakupro.yaml"
        target.write_text("style:\n  font_size: 99\n", encoding="utf-8")
        assert self._run("--init-config", "-f") == 0
        assert target.read_text(encoding="utf-8") == EXAMPLE_CONFIG.read_text(
            encoding="utf-8"
        )

    def test_config_flag_sets_destination(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        dest = tmp_path / "nested" / "my.yaml"
        dest.parent.mkdir()
        assert self._run("--init-config", "-c", str(dest)) == 0
        assert dest.exists()

    def test_function_returns_zero_on_success(self, tmp_path):
        dest = tmp_path / "out.yaml"
        assert init_config(str(dest)) == 0
        assert dest.exists()

    def test_missing_packaged_template_returns_error(self, tmp_path, monkeypatch):
        """模板缺失（打包事故）应返回失败码，而不是抛未捕获异常。"""
        monkeypatch.chdir(tmp_path)
        with patch("danmakupro.cli.EXAMPLE_CONFIG", tmp_path / "absent.yaml"):
            assert init_config() == 1

    def test_unwritable_destination_returns_error(self, tmp_path, monkeypatch):
        """目标被同名目录占位时写入会失败，需返回失败码。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "danmakupro.yaml").mkdir()
        assert self._run("--init-config", "-f") == 1

    def test_missing_positionals_exit_code_is_2(self, tmp_path, monkeypatch):
        """video/xml 改为可选后，缺参仍须以退出码 2 失败（与 argparse 一致）。"""
        monkeypatch.chdir(tmp_path)
        assert self._run() == 2

    def test_only_video_provided_still_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert self._run("only.mp4") == 2
