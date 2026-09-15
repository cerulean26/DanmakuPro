"""validation.py 单元测试

测试 validate_video_input、validate_xml_input、validate_output_path
与覆盖确认 confirm_overwrite 的全部分支路径。
"""

import sys
from pathlib import Path

import pytest

from danmakupro.utils.validation import (
    validate_video_input,
    validate_xml_input,
    validate_output_path,
    confirm_overwrite,
    _human_size,
    SUPPORTED_VIDEO_EXTS,
    SUPPORTED_OUTPUT_EXTS,
)
from danmakupro.errors import InputError


# =============================================================================
# validate_video_input
# =============================================================================


class TestValidateVideoInput:
    """测试 validate_video_input：视频文件存在性、类型和格式校验。"""

    def test_valid_mp4(self, tmp_path):
        """存在且格式支持的 .mp4 文件应通过校验。"""
        p = tmp_path / "test.mp4"
        p.touch()
        validate_video_input(str(p))

    def test_valid_flv(self, tmp_path):
        """存在且格式支持的 .flv 文件应通过校验。"""
        p = tmp_path / "test.flv"
        p.touch()
        validate_video_input(str(p))

    def test_file_not_exist(self):
        """不存在的文件应抛出 InputError。"""
        with pytest.raises(InputError, match="视频文件不存在"):
            validate_video_input("/nonexistent/path/video.mp4")

    def test_path_is_directory(self, tmp_path):
        """路径是目录时应抛出 InputError。"""
        with pytest.raises(InputError, match="视频路径是目录"):
            validate_video_input(str(tmp_path))

    def test_unsupported_extension(self, tmp_path):
        """不支持的扩展名应抛出 InputError。"""
        p = tmp_path / "test.txt"
        p.touch()
        with pytest.raises(InputError, match="不支持的视频格式"):
            validate_video_input(str(p))

    def test_all_supported_extensions(self, tmp_path):
        """所有 SUPPORTED_VIDEO_EXTS 都应通过校验。"""
        for ext in SUPPORTED_VIDEO_EXTS:
            p = tmp_path / f"test{ext}"
            p.touch()
            validate_video_input(str(p))

    def test_uppercase_extension(self, tmp_path):
        """大写扩展名应被归一化处理（.MP4 → .mp4）。"""
        p = tmp_path / "test.MP4"
        p.touch()
        validate_video_input(str(p))


# =============================================================================
# validate_xml_input
# =============================================================================


class TestValidateXmlInput:
    """测试 validate_xml_input：XML 文件校验。"""

    def test_valid_xml(self, tmp_path):
        """存在且扩展名为 .xml 的文件应通过校验。"""
        p = tmp_path / "danmaku.xml"
        p.touch()
        validate_xml_input(str(p))

    def test_file_not_exist(self):
        """不存在的文件应抛出 InputError。"""
        with pytest.raises(InputError, match="弹幕 XML 文件不存在"):
            validate_xml_input("/nonexistent/path/danmaku.xml")

    def test_path_is_directory(self, tmp_path):
        """路径是目录时应抛出 InputError。"""
        with pytest.raises(InputError, match="弹幕 XML 路径是目录"):
            validate_xml_input(str(tmp_path))

    def test_not_xml_extension(self, tmp_path):
        """非 .xml 扩展名应抛出 InputError。"""
        p = tmp_path / "danmaku.json"
        p.touch()
        with pytest.raises(InputError, match="不支持的弹幕格式"):
            validate_xml_input(str(p))

    def test_uppercase_xml(self, tmp_path):
        """大写 .XML 扩展名应通过校验。"""
        p = tmp_path / "danmaku.XML"
        p.touch()
        validate_xml_input(str(p))


# =============================================================================
# validate_output_path
# =============================================================================


class TestValidateOutputPath:
    """测试 validate_output_path：输出路径校验。"""

    def test_valid_output(self, tmp_path):
        """输出目录存在且格式支持时应通过校验。"""
        p = tmp_path / "output.mp4"
        validate_output_path(str(p))

    def test_parent_dir_not_exist(self):
        """父目录不存在时应抛出 InputError。"""
        with pytest.raises(InputError, match="输出目录不存在"):
            validate_output_path("/nonexistent/dir/output.mp4")

    def test_unsupported_extension(self, tmp_path):
        """不支持的扩展名应抛出 InputError。"""
        p = tmp_path / "output.txt"
        with pytest.raises(InputError, match="不支持的输出格式"):
            validate_output_path(str(p))

    def test_file_exists_confirm_accepted(self, tmp_path):
        """确认函数返回 True 时应通过校验（按覆盖处理）。"""
        p = tmp_path / "output.mp4"
        p.touch()
        asked: list[Path] = []

        def _confirm(path: Path) -> bool:
            asked.append(path)
            return True

        validate_output_path(str(p), confirm=_confirm)
        assert asked == [p]

    def test_file_exists_confirm_rejected(self, tmp_path):
        """确认函数返回 False 时应抛出 InputError，并给出两条出路。"""
        p = tmp_path / "output.mp4"
        p.touch()
        with pytest.raises(InputError) as exc:
            validate_output_path(str(p), confirm=lambda _p: False)
        message = str(exc.value)
        assert "已取消覆盖" in message
        assert "-f" in message
        assert "-o" in message

    def test_file_exists_force_skips_confirm(self, tmp_path):
        """指定 force 时直接覆盖，不应询问用户。"""
        p = tmp_path / "output.mp4"
        p.touch()

        def _boom(_path: Path) -> bool:
            raise AssertionError("force=True 时不应询问")

        validate_output_path(str(p), force=True, confirm=_boom)

    def test_file_missing_skips_confirm(self, tmp_path):
        """文件不存在时不应询问用户。"""
        p = tmp_path / "brand_new.mp4"

        def _boom(_path: Path) -> bool:
            raise AssertionError("文件不存在时不应询问")

        validate_output_path(str(p), confirm=_boom)

    def test_all_supported_output_extensions(self, tmp_path):
        """所有 SUPPORTED_OUTPUT_EXTS 都应通过校验。"""
        for ext in SUPPORTED_OUTPUT_EXTS:
            p = tmp_path / f"output{ext}"
            validate_output_path(str(p))

    def test_file_not_exists_no_error(self, tmp_path):
        """文件不存在时不应报错。"""
        p = tmp_path / "new_output.mp4"
        validate_output_path(str(p))


# =============================================================================
# confirm_overwrite
# =============================================================================


class _FakeStdin:
    """最小可用的 stdin 替身：只实现 isatty()，足以穿过终端判定。"""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def log_messages():
    """收集 loguru 的日志文本（loguru 不经过标准 logging，caplog 抓不到）。"""
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(
        lambda m: messages.append(m.record["message"]), level="WARNING"
    )
    try:
        yield messages
    finally:
        logger.remove(sink_id)


class TestHumanSize:
    """测试 _human_size：体积展示的各量级分支。"""

    def test_units(self):
        """B/KB/MB/GB/TB 五个量级都应格式化正确。"""
        assert _human_size(0) == "0 B"
        assert _human_size(512) == "512 B"
        assert _human_size(2048) == "2.0 KB"
        assert _human_size(5 * 1024**2) == "5.0 MB"
        assert _human_size(3 * 1024**3) == "3.0 GB"
        assert _human_size(2 * 1024**4) == "2.0 TB"


class TestConfirmOverwrite:
    """测试 confirm_overwrite：交互式覆盖确认的各条应答路径。

    注意：本类的用例必须先把目标文件真实创建出来。文件不存在时
    confirm_overwrite 会走「询问前文件刚好消失」的防御分支直接放行，
    根本不读终端 —— 那样测出来的只是那条竞态路径。
    """

    @staticmethod
    def _interactive(monkeypatch, *answers):
        """把 stdin 伪装成交互式终端，并按顺序返回给定的应答。

        Args:
            monkeypatch: pytest 的 monkeypatch
            *answers: 各次 input() 的返回值；多于一个可用于测试「无效输入重问」

        Returns:
            记录每次 input() 提示语的列表，供调用方断言「确实问了用户」。
        """
        monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))
        remaining = list(answers)
        asks: list[str] = []

        def _input(prompt: str = "") -> str:
            asks.append(prompt)
            if not remaining:
                raise AssertionError("input() 被调用的次数超出预期")
            return remaining.pop(0)

        monkeypatch.setattr("builtins.input", _input)
        return asks

    @staticmethod
    def _existing(tmp_path):
        """创建一个待覆盖的空输出文件。"""
        p = tmp_path / "out.mp4"
        p.touch()
        return p

    def test_answer_yes(self, tmp_path, monkeypatch):
        """回答 y 应返回 True。"""
        asks = self._interactive(monkeypatch, "y")
        assert confirm_overwrite(self._existing(tmp_path)) is True
        assert len(asks) == 1

    def test_answer_yes_spelled_out(self, tmp_path, monkeypatch):
        """回答 yes 应返回 True。"""
        asks = self._interactive(monkeypatch, "yes")
        assert confirm_overwrite(self._existing(tmp_path)) is True
        assert len(asks) == 1

    def test_answer_is_case_insensitive(self, tmp_path, monkeypatch):
        """大写 Y（含首尾空白）应返回 True。"""
        self._interactive(monkeypatch, "  Y  ")
        assert confirm_overwrite(self._existing(tmp_path)) is True

    def test_answer_no(self, tmp_path, monkeypatch):
        """回答 n 应返回 False。"""
        asks = self._interactive(monkeypatch, "n")
        assert confirm_overwrite(self._existing(tmp_path)) is False
        assert len(asks) == 1

    def test_answer_no_spelled_out(self, tmp_path, monkeypatch):
        """回答 no 应返回 False。"""
        self._interactive(monkeypatch, "no")
        assert confirm_overwrite(self._existing(tmp_path)) is False

    def test_enter_defaults_to_no(self, tmp_path, monkeypatch):
        """直接回车应取默认值「否」——覆盖是不可逆操作，默认必须保守。"""
        self._interactive(monkeypatch, "")
        assert confirm_overwrite(self._existing(tmp_path)) is False

    def test_invalid_answer_reprompts(self, tmp_path, monkeypatch):
        """无法识别的输入应重新询问，而不是当作拒绝或接受。"""
        asks = self._interactive(monkeypatch, "maybe", "y")
        assert confirm_overwrite(self._existing(tmp_path)) is True
        assert len(asks) == 2

    def test_eof_is_treated_as_no(self, tmp_path, monkeypatch):
        """输入流被关闭（EOF）按「不覆盖」处理，不让异常逃到上层。"""
        monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))

        def _raise(*_a):
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise)
        assert confirm_overwrite(self._existing(tmp_path)) is False

    def test_keyboard_interrupt_is_treated_as_no(self, tmp_path, monkeypatch):
        """Ctrl+C 打断询问按「不覆盖」处理，不让 KeyboardInterrupt 逃逸。"""
        monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))

        def _raise(*_a):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _raise)
        assert confirm_overwrite(self._existing(tmp_path)) is False

    def test_non_interactive_never_prompts(self, tmp_path, monkeypatch, log_messages):
        """非交互式终端不询问（input() 会拿到 EOF 或永久阻塞），直接按拒绝处理。"""
        monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=False))

        def _boom(*_a):
            raise AssertionError("非交互环境不应调用 input()")

        monkeypatch.setattr("builtins.input", _boom)
        assert confirm_overwrite(self._existing(tmp_path)) is False
        assert any("无法询问是否覆盖" in m for m in log_messages)

    def test_missing_stdin_never_prompts(self, tmp_path, monkeypatch):
        """stdin 为 None（pythonw / 无控制台）时同样不询问。"""
        monkeypatch.setattr(sys, "stdin", None)
        assert confirm_overwrite(self._existing(tmp_path)) is False

    def test_zero_byte_file_is_reported_as_leftover(
        self, tmp_path, monkeypatch, log_messages
    ):
        """0 字节文件应在提示里点明「疑似上次失败的残留」，帮用户判断。"""
        self._interactive(monkeypatch, "n")
        assert confirm_overwrite(self._existing(tmp_path)) is False
        assert any("0 字节" in m and "残留" in m for m in log_messages)

    def test_sized_file_reports_human_readable_size(
        self, tmp_path, monkeypatch, log_messages
    ):
        """有内容的文件应展示可读体积与最后修改时间。"""
        self._interactive(monkeypatch, "n")
        p = tmp_path / "out.mp4"
        p.write_bytes(b"x" * 2048)
        assert confirm_overwrite(p) is False
        assert any("2.0 KB" in m and "最后修改" in m for m in log_messages)

    def test_file_vanished_mid_prompt_is_overwritable(self, tmp_path, monkeypatch):
        """询问前文件刚好消失：没有可覆盖的对象，按可覆盖放行。

        这里刻意不创建文件 —— 走的正是 stat 失败的那条竞态防御分支。
        """
        self._interactive(monkeypatch, "y")
        assert confirm_overwrite(tmp_path / "gone.mp4") is True


class TestPromptOrdering:
    """测试「日志先写出、交互提示后显示」的顺序契约。

    背景（2026-09-16 真机现象）：stderr sink 配了 enqueue=True，日志由 loguru
    的后台线程异步写出。若不在显示提示前排空队列，用户先看到
    「是否覆盖该文件？[y/N] 」，随后才看到迟到的 WARNING 粘在同一行。
    """

    def test_queue_drained_before_prompt(self, tmp_path, monkeypatch):
        """排空队列（flush_logs）必须在显示 prompt 之前发生。"""
        events: list[str] = []

        def _fake_flush() -> None:
            events.append("flush")

        monkeypatch.setattr("danmakupro.utils.validation.flush_logs", _fake_flush)
        monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))

        def _input(prompt: str = "") -> str:
            events.append("prompt")
            return "n"

        monkeypatch.setattr("builtins.input", _input)
        p = tmp_path / "out.mp4"
        p.touch()
        assert confirm_overwrite(p) is False
        assert events == ["flush", "prompt"], f"调用顺序错误: {events}"

    def test_warning_written_before_prompt(self, tmp_path, monkeypatch):
        """端到端：用与真机相同的 enqueue=True 管道，WARNING 必须早于 prompt 写出。

        刻意不 sleep 等待后台线程 —— 只有真正的排空才能保证顺序，加 sleep
        会让这条断言变成为时序妥协的假测试。
        """
        from loguru import logger

        events: list[tuple[str, str]] = []
        sink_id = logger.add(
            lambda m: events.append(("log", m.record["message"])),
            level="WARNING",
            format="{message}",
            enqueue=True,
        )
        try:
            monkeypatch.setattr(sys, "stdin", _FakeStdin(tty=True))

            def _input(prompt: str = "") -> str:
                events.append(("prompt", prompt))
                return "n"

            monkeypatch.setattr("builtins.input", _input)
            p = tmp_path / "out.mp4"
            p.write_bytes(b"x" * 16)
            assert confirm_overwrite(p) is False
        finally:
            logger.remove(sink_id)

        kinds = [kind for kind, _ in events]
        assert kinds == ["log", "prompt"], f"WARNING 未先于提示写出: {events}"
