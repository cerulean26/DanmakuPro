"""端到端压制用例（真实 ffmpeg，标记 slow）

覆盖「输入视频 + 弹幕 XML → 可播放输出文件」的完整链路：真实调用
ffmpeg / ffprobe 压制一段 2 秒合成视频，再反过来检查产物本身 ——
分辨率、帧数、时长、以及**像素内容里是否真的有弹幕被画上去**。

为什么必须要有这一层：其余 300 多个单测把 subprocess 全部 mock 掉了，
只能验证「我们期望拼出的命令」是否正确，验证不了「ffmpeg 是否接受这条
命令」。以下问题只会在真机暴露，单测永远发现不了：

- 滤镜图语法错误 / overlay 的输入标签写错 → ffmpeg 直接以非 0 退出
- 帧数或帧率口径算错 → 产物时长对不上（弹幕时间轴随之整体偏移）
- 弹幕层根本没叠加成功 → 产物能播，但画面里一条弹幕都没有

运行方式（CI 未安装 ffmpeg，故默认被 `-m "not gpu and not slow"` 排除）::

    pytest tests/test_e2e_burn.py -m slow

未安装 ffmpeg 的环境会自动 skip，不产生假失败。
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from danmakupro.cli import main
from danmakupro.config.models import DanmakuConfig, EncodeParams, SystemParams
from danmakupro.core.burner import DanmakuBurner

# =============================================================================
# 常量与前置条件
# =============================================================================

#: 合成测试视频参数。320x240 已是 16 的整数倍，不会被 system.video_alignment
#: 改变尺寸，因此断言里的分辨率可以写死。
SRC_W = 320
SRC_H = 240
SRC_FPS = 30
SRC_SECONDS = 2
SRC_FRAMES = SRC_FPS * SRC_SECONDS

#: 弹幕事件数。刻意远低于发射能力上限（文本 3 条/0.5s = 6 条/秒 vs 需求
#: 2 条/秒），使「全部发射」成为确定结论 —— 否则这条断言会随自适应加速
#: 策略的调整而随机失败。
EXPECTED_TEXT = 4
EXPECTED_GIFT = 1

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
        reason="需要真实 ffmpeg / ffprobe",
    ),
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    """用 lavfi 合成一段 2 秒测试视频，不依赖仓库里的 source/ 素材。"""
    out = tmp_path_factory.mktemp("e2e") / "src.mp4"
    r = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi",
        "-i", f"testsrc=size={SRC_W}x{SRC_H}:rate={SRC_FPS}:duration={SRC_SECONDS}",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast",
        str(out),
    ])
    assert r.returncode == 0, f"合成测试视频失败:\n{r.stderr}"
    assert out.exists() and out.stat().st_size > 0
    return out


@pytest.fixture(scope="module")
def sample_xml(tmp_path_factory) -> Path:
    """抖音格式弹幕文件：4 条文本 + 1 个礼物，全部落在 0~2s 内。"""
    out = tmp_path_factory.mktemp("e2e") / "danmaku.xml"
    out.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<i>\n"
        '  <d p="0.300,0,0,0,0,0,0" user="小星">第一条测试弹幕</d>\n'
        '  <d p="0.700,0,0,0,0,0,0" user="测试用户">第二条测试弹幕</d>\n'
        '  <d p="1.100,0,0,0,0,0,0" user="小星">第三条测试弹幕</d>\n'
        '  <d p="1.500,0,0,0,0,0,0" user="测试用户">第四条测试弹幕</d>\n'
        '  <gift ts="0.500" user="小星" giftname="小心心" giftcount="1" price="2000"/>\n'
        "</i>\n",
        encoding="utf-8",
    )
    return out


@pytest.fixture(scope="module")
def empty_xml(tmp_path_factory) -> Path:
    """零事件的弹幕文件 —— 像素断言的对照组。

    必须有这个对照组：源视频帧与产物帧都要经过 h264 编解码和 `scale` 滤镜，
    两者的差异未必来自弹幕。跑一遍完全相同的管线但一条弹幕都不发，才能把
    「弹幕造成的差异」从「编解码造成的差异」里分离出来。
    """
    out = tmp_path_factory.mktemp("e2e") / "empty.xml"
    out.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<i></i>\n',
        encoding="utf-8",
    )
    return out


@pytest.fixture(scope="module")
def late_event_xml(tmp_path_factory) -> Path:
    """只含一条「接近片尾」事件的弹幕文件 —— 探测弹幕层是否被截短。

    若渲染帧数少于视频帧数，`overlay` 的 framesync 会把弹幕层的最后一帧
    **重复**到视频长度：产物依旧是 60 帧 / 2.0s，帧数与时长断言完全看不出
    问题，但后半段弹幕会「冻住」。把唯一的弹幕放在 1.8s，就能定点区分：

    - 层是完整的 → 1.9s 时这条弹幕必然在屏（实测差异 20.2）
    - 层被截短   → 这条根本没被渲染（实测差异 0.000）
    """
    out = tmp_path_factory.mktemp("e2e") / "late.xml"
    out.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<i>\n'
        '  <d p="1.800,0,0,0,0,0,0" user="小星">尾部事件测试弹幕</d>\n'
        "</i>\n",
        encoding="utf-8",
    )
    return out


@pytest.fixture
def empty_assets_dir(tmp_path) -> Path:
    """空资源目录。

    用例只发文本弹幕与一个礼物，礼物图片缺失时 `_build_gift_segments`
    会跳过图片段落（layout_builder.py:247 的 `in self.gift_cache` 判断），
    所以整个用例不依赖 assets/ —— CI 与任何干净克隆都能跑。
    """
    d = tmp_path / "assets"
    (d / "emoji").mkdir(parents=True)
    (d / "gift").mkdir(parents=True)
    return d


@pytest.fixture
def cli_config_yaml(tmp_path, empty_assets_dir) -> Path:
    """CLI 用最小配置。

    必须显式指定：`load_config(None)` 会去当前目录找 `danmakupro.yaml`，
    那是开发者本机调过的配置，会让断言随机器而变。
    """
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "system:\n"
        f"  assets_dir: {empty_assets_dir.as_posix()}\n"
        "encode:\n"
        "  cpu_preset: ultrafast\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def e2e_config(empty_assets_dir) -> DanmakuConfig:
    """直接构造的配置：编码固定走 CPU、资源目录指向空目录。

    与 cli_config_yaml 同源，但绕过 YAML —— 测引擎本身时不必经过配置解析，
    这样配置解析一旦出问题，失败会落在 CLI 用例上而不是这儿。
    """
    return DanmakuConfig(
        encode=EncodeParams(cpu_preset="ultrafast"),
        system=SystemParams(assets_dir=str(empty_assets_dir)),
    )


@pytest.fixture
def log_sink():
    """收集 loguru 的日志消息文本。"""
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(
        lambda m: messages.append(m.record["message"]), level="INFO",
    )
    try:
        yield messages
    finally:
        logger.remove(sink_id)


# =============================================================================
# 辅助断言函数
# =============================================================================

def _ffprobe(path: Path) -> tuple[dict, dict]:
    """返回 (视频流信息, 容器信息)。"""
    r = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_frames,codec_name,pix_fmt",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    assert r.returncode == 0, f"ffprobe 失败:\n{r.stderr}"
    data = json.loads(r.stdout)
    assert data.get("streams"), f"产物里没有视频流: {data}"
    return data["streams"][0], data.get("format", {})


def _extract_png(video: Path, t: float, dest: Path) -> Path:
    r = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", str(t), "-i", str(video), "-frames:v", "1", str(dest),
    ])
    assert r.returncode == 0, f"抽帧失败 ({video} @ {t}s):\n{r.stderr}"
    return dest


def _mean_channel_diff(a: Path, b: Path, step: int = 2) -> float:
    """逐像素（隔 step 采样）比较两张同尺寸图片的平均单通道绝对差。

    用 QImage 而非 PIL/numpy，避免为测试引入新依赖（PySide6 已是运行时依赖）。
    """
    from PySide6.QtGui import QImage

    ia, ib = QImage(str(a)), QImage(str(b))
    assert not ia.isNull(), f"无法读取图片: {a}"
    assert not ib.isNull(), f"无法读取图片: {b}"
    assert (ia.width(), ia.height()) == (ib.width(), ib.height()), (
        f"尺寸不一致: {ia.width()}x{ia.height()} vs {ib.width()}x{ib.height()}"
    )

    total = 0
    n = 0
    for y in range(0, ia.height(), step):
        for x in range(0, ia.width(), step):
            pa, pb = ia.pixel(x, y), ib.pixel(x, y)
            total += (
                abs(((pa >> 16) & 0xFF) - ((pb >> 16) & 0xFF))
                + abs(((pa >> 8) & 0xFF) - ((pb >> 8) & 0xFF))
                + abs((pa & 0xFF) - (pb & 0xFF))
            )
            n += 1
    return total / (3 * n)


# =============================================================================
# 用例
# =============================================================================

class TestEndToEndBurn:
    """真实压制链路。"""

    def test_cli_run_produces_playable_mp4(
        self, qapp, sample_video, sample_xml, tmp_path, cli_config_yaml,
    ):
        """走完整 CLI 入口压制，产物必须是分辨率/帧数/时长都正确的可解码 mp4。

        这是唯一一条覆盖「argparse → 配置加载 → 压制引擎 → ffmpeg」全链路的
        用例，也是唯一能证明发布出去的命令行真的能跑通的证据。
        """
        out = tmp_path / "out.mp4"
        argv = [
            "danmakupro", str(sample_video), str(sample_xml),
            "-o", str(out), "--encode", "cpu", "-c", str(cli_config_yaml),
        ]

        # 只 patch cli 模块对 QApplication 的引用：main() 的 finally 会
        # quit() + deleteLater()，而 qapp 是 session 级共享实例，被销毁会
        # 波及同进程的后续用例。这不是在回避被测逻辑 —— 退出时的 Qt 拆除
        # 与压制链路无关，压制的产物校验才是本用例的目的。
        with patch("sys.argv", argv), patch("danmakupro.cli.QApplication"):
            main()  # 成功路径正常返回，不抛 SystemExit

        assert out.exists(), f"未生成输出文件: {out}"
        assert out.stat().st_size > 0, "输出文件是 0 字节"

        stream, fmt = _ffprobe(out)
        assert int(stream["width"]) == SRC_W
        assert int(stream["height"]) == SRC_H
        assert stream["codec_name"] == "h264"
        assert int(stream["nb_frames"]) == SRC_FRAMES, (
            f"帧数不符：期望 {SRC_FRAMES}，实际 {stream['nb_frames']}"
        )
        duration = float(fmt["duration"])
        assert abs(duration - SRC_SECONDS) < 0.1, (
            f"时长不符：期望 {SRC_SECONDS}s，实际 {duration}s"
        )

    def test_burner_run_renders_danmaku_into_frames(
        self, qapp, sample_video, sample_xml, empty_xml, late_event_xml,
        tmp_path, log_sink, e2e_config,
    ):
        """弹幕必须真的画进画面、全部发射、且铺满整个视频时长。

        三层断言，缺一不可：
        1. 统计层 —— 发射数与事件数相等，证明没有静默丢弹幕；
        2. 像素层 —— 与**同一管线的无弹幕对照组**逐帧比较。只断言「产物
           能解码」远远不够：弹幕层完全没叠上去时，产物依然能被解码，
           帧数与时长也依然正确。像素层又分两段：
           - 空窗期（首条弹幕之前）差异必须为 0，证明叠加层在没有弹幕时
             是彻底的 no-op；
           - 在屏期必须显著有差异，证明叠加真的发生了。
        3. 尾部活性 —— 帧数与时长断言**抓不到**「弹幕层被截短」：overlay
           会用最后一帧补齐时长，产物仍是 60 帧 / 2.0s。必须用定点探针
           才能发现（见 late_event_xml）。
        """
        out = tmp_path / "burned.mp4"
        burner = DanmakuBurner(
            video_in=str(sample_video), xml_in=str(sample_xml),
            video_out=str(out), encode_mode="cpu",
            config=e2e_config,
        )
        burner.run()

        assert out.exists() and out.stat().st_size > 0

        # ── 1. 统计层：全部发射 ──
        done = [m for m in log_sink if m.startswith("完成:")]
        assert done, f"未捕获到完成统计日志，实际日志: {log_sink}"
        assert f"弹幕 {EXPECTED_TEXT}/{EXPECTED_TEXT}" in done[-1], done[-1]
        assert f"礼物 {EXPECTED_GIFT}/{EXPECTED_GIFT}" in done[-1], done[-1]

        # ── 2. 像素层：与无弹幕对照组比较 ──
        stream, fmt = _ffprobe(out)
        assert int(stream["nb_frames"]) == SRC_FRAMES
        assert abs(float(fmt["duration"]) - SRC_SECONDS) < 0.1

        control = tmp_path / "control.mp4"
        DanmakuBurner(
            video_in=str(sample_video), xml_in=str(empty_xml),
            video_out=str(control), encode_mode="cpu",
            config=e2e_config,
        ).run()
        assert control.exists() and control.stat().st_size > 0

        def _diff_at(t: float, tag: str) -> float:
            return _mean_channel_diff(
                _extract_png(out, t, tmp_path / f"burned_{tag}.png"),
                _extract_png(control, t, tmp_path / f"control_{tag}.png"),
            )

        # 第一条弹幕在 0.3s，故 0.05s 时画面上必然空无一物；
        # 1.00s 时 0.3/0.7s 的文本弹幕与 0.5s 的礼物都应在屏上。
        diff_before = _diff_at(0.05, "before")
        diff_peak = _diff_at(1.00, "peak")
        print(
            f"\n[e2e 像素] 空窗期(0.05s)={diff_before:.3f}, "
            f"在屏期(1.00s)={diff_peak:.3f}"
        )

        # 空窗期两条产物帧必须逐位相同：同一管线、同一背景输入、同一编码参数，
        # 唯一变量就是弹幕层 —— 没有弹幕时它必须是完全透明的 no-op。
        # 这一条能拦住「整层被半透明涂黑」「overlay 时间轴错位导致弹幕提前出现」
        # 这类缺陷，仅靠「有弹幕时画面有差异」是拦不住的。
        assert diff_before < 0.01, (
            f"无弹幕时段产物与对照仍有差异（平均通道差 {diff_before:.3f}），"
            "说明弹幕层在空窗期并非完全透明"
        )
        assert diff_peak > 1.0, (
            f"有弹幕与无弹幕的产物帧几乎相同（平均通道差 {diff_peak:.3f}），"
            "说明弹幕层没有被叠加到画面里"
        )

        # ── 3. 尾部活性：弹幕层必须铺满整个视频时长 ──
        # 见 late_event_xml 的说明：帧数断言抓不到「层被截短」，这一条才能。
        late = tmp_path / "late.mp4"
        DanmakuBurner(
            video_in=str(sample_video), xml_in=str(late_event_xml),
            video_out=str(late), encode_mode="cpu",
            config=e2e_config,
        ).run()

        diff_late = _mean_channel_diff(
            _extract_png(late, 1.90, tmp_path / "late_end.png"),
            _extract_png(control, 1.90, tmp_path / "control_end.png"),
        )
        diff_late_early = _mean_channel_diff(
            _extract_png(late, 0.60, tmp_path / "late_early.png"),
            _extract_png(control, 0.60, tmp_path / "control_early.png"),
        )
        print(f"[e2e 像素] 尾部事件: 1.90s={diff_late:.3f}, 0.60s={diff_late_early:.3f}")

        assert diff_late > 1.0, (
            f"1.8s 的弹幕在 1.90s 没有出现在画面上（平均通道差 {diff_late:.3f}）。"
            "弹幕层可能被截短（frame 数少于视频帧数，overlay 用最后一帧补齐）"
        )
        assert diff_late_early < 0.01, (
            f"1.8s 的弹幕提前出现在了 0.60s（平均通道差 {diff_late_early:.3f}），"
            "弹幕时间轴与视频未对齐"
        )

    def test_check_mode_reports_without_writing_output(
        self, qapp, sample_video, sample_xml, tmp_path, e2e_config,
    ):
        """`--check` 只出报告，绝不产出文件。

        这条同时守着一个已修过的缺陷：check_only 必须跳过输出路径校验，
        否则上一次失败留下的残缺产物会把「检查」直接挡在门外。
        """
        out = tmp_path / "never_created.mp4"

        burner = DanmakuBurner(
            video_in=str(sample_video), xml_in=str(sample_xml),
            video_out=str(out), encode_mode="cpu",
            config=e2e_config, check_only=True,
        )
        burner.check()

        assert not out.exists(), "检查模式不应产生任何输出文件"

    def test_existing_output_is_rejected_without_force(
        self, qapp, sample_video, sample_xml, tmp_path, e2e_config,
    ):
        """输出已存在且未指定 force 时必须拒绝，避免误覆盖用户成片。"""
        from danmakupro.errors import InputError

        out = tmp_path / "occupied.mp4"
        out.write_bytes(b"existing")

        with pytest.raises(InputError, match="已存在"):
            DanmakuBurner(
                video_in=str(sample_video), xml_in=str(sample_xml),
                video_out=str(out), encode_mode="cpu",
                config=e2e_config,
            )
        # 原有文件必须原封不动
        assert out.read_bytes() == b"existing"
