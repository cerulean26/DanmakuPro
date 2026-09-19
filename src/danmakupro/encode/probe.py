"""视频元数据探测

从 ffprobe 读取尺寸、帧数、编码格式与时长，并据此定出渲染用的帧率口径。
本模块不持有状态，全部按输入路径与超时显式传参，便于单独测试与复用。
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from typing import NamedTuple

from loguru import logger

#: 探测子进程最小超时（秒）。
PROBE_TIMEOUT_MIN = 1

#: 帧率修正的相对偏差阈值，超过才提示，避免 CFR 舍入刷屏。
FPS_LOG_TOLERANCE = 0.005

#: 帧率修正的可信区间下限：比值低于此值则回落 r_frame_rate。
_FPS_SANITY_LO = 1 / 3
#: 帧率修正的可信区间上限。
_FPS_SANITY_HI = 3.0


class VideoInfo(NamedTuple):
    """一份输入视频的元数据。

    Attributes:
        width: 画面宽度
        height: 画面高度
        fps: 渲染用帧率，可能不等于容器的 r_frame_rate（口径见 resolve_render_fps）
        frames: 总帧数
        codec: 输入的编码格式（ffprobe 的 codec_name）；探不到时为 None
    """

    width: int
    height: int
    fps: float
    frames: int
    codec: str | None


def run_probe(
    cmd: list[str], timeout: float, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """统一的探测子进程调用。

    探测一律捕获输出、按文本解码并设超时，差异只在 check，集中于此免得每处
    重复同样的四个关键字。

    Args:
        cmd: 完整命令行
        timeout: 子进程超时（秒）
        check: 非 0 退出码是否抛 CalledProcessError。靠返回码判断可用性的
            试探传 False。

    Returns:
        已捕获 stdout / stderr 的 CompletedProcess，stdout 为 str。
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def parse_frame_rate(raw: str | None) -> float:
    """把 ffprobe 的 "num/den" 形式转成浮点数。

    Args:
        raw: 形如 "22/1" 的字符串；缺失或非法时返回 0.0

    Returns:
        帧率；无法解析时返回 0.0（调用方以 > 0 判断是否有效）
    """
    if not raw:
        return 0.0
    num, _, den = raw.partition("/")
    try:
        numerator = int(num)
        denominator = int(den) if den else 1
    except ValueError:
        return 0.0
    if denominator == 0:
        return 0.0
    return numerator / denominator


def resolve_render_fps(nominal_fps: float, frames: int, duration: float) -> float:
    """确定渲染用帧率，优先采用 frames/duration 以对齐 VFR 源真实时长。

    标称帧率在 VFR 源上偏离实际，会导致弹幕时间轴与画面错位。详见 ADR-0001。
    """
    if nominal_fps <= 0 or frames <= 0 or duration <= 0:
        return nominal_fps
    real_fps = frames / duration
    if real_fps <= 0:
        return nominal_fps
    ratio = real_fps / nominal_fps
    if not (_FPS_SANITY_LO <= ratio <= _FPS_SANITY_HI):
        return nominal_fps
    return real_fps


@functools.lru_cache(maxsize=None)
def probe_input_codec(video_in: str, timeout: int) -> str | None:
    """输入视频的编码格式（ffprobe codec_name），探测失败返回 None。

    结果带进程级缓存，同一份输入的硬解判据不会被反复起子进程。

    Args:
        video_in: 输入视频路径
        timeout: 子进程超时（秒）

    Returns:
        编码格式名；ffprobe 缺失、探测失败或输出为空时返回 None。
    """
    if shutil.which("ffprobe") is None:
        return None
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=nw=1:nk=1",
        video_in,
    ]
    try:
        result = run_probe(cmd, timeout)
        name = result.stdout.strip().splitlines()[0].strip()
    except (
        subprocess.SubprocessError,
        OSError,
        ValueError,
        IndexError,
    ):
        return None
    return name or None


def probe_packet_count(video_in: str, timeout: float) -> int | None:
    """探测视频流的包数，作为真实帧数的低成本来源。

    容器字段 ``nb_frames`` 在部分封装下恒缺失，此时帧数只能按标称帧率推算；
    而推算值与标称同源，``frames / duration`` 会把标称约掉，帧率口径修正
    随之失效。本函数提供一个独立于标称的真实帧数来源。

    Args:
        video_in: 输入视频路径
        timeout: 子进程超时（秒）

    Returns:
        包数；探测失败、字段缺失或结果非正时返回 None，调用方据此回落到
        标称推算。原则是「宁可不修正，也不要用错的值」。

    选型与实测依据见 ``docs/decisions/ADR-0001-render-fps-and-frame-count.md``。
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_packets",
        "-show_entries",
        "stream=nb_read_packets",
        "-of",
        "json",
        video_in,
    ]
    try:
        result = run_probe(cmd, timeout)
        data = json.loads(result.stdout)
        count = int(data["streams"][0]["nb_read_packets"])
    except (
        subprocess.SubprocessError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
    ):
        return None
    return count if count > 0 else None


def read_video_info(video_in: str, timeout: float) -> VideoInfo:
    """读取视频元数据，返回 VideoInfo。参数直接对应 ffprobe 子进程超时。"""
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "未找到 ffprobe，请先安装 FFmpeg:\n"
            "  Windows: winget install ffmpeg 或 scoop install ffmpeg\n"
            "  其他系统: https://ffmpeg.org/download.html"
        )
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames,codec_name:format=duration",
        "-of",
        "json",
        video_in,
    ]
    result = run_probe(cmd, timeout)
    data = json.loads(result.stdout)
    info = data["streams"][0]
    codec = str(info.get("codec_name") or "") or None
    nominal_fps = parse_frame_rate(info.get("r_frame_rate"))

    # nb_frames 在部分封装下缺失（FLV 恒如此），不能无条件 int()。
    raw_frames = info.get("nb_frames")
    try:
        frames = int(raw_frames) if raw_frames else 0
    except (TypeError, ValueError):
        frames = 0

    try:
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        duration = 0.0

    if frames == 0:
        # nb_frames 缺失时先探真实包数，探不到再按标称推算（此时帧数修正失效）。
        probed = probe_packet_count(video_in, max(PROBE_TIMEOUT_MIN, timeout))
        frames = probed if probed is not None else int(duration * nominal_fps)

    fps = resolve_render_fps(nominal_fps, frames, duration)
    if nominal_fps > 0 and abs(fps - nominal_fps) / nominal_fps > FPS_LOG_TOLERANCE:
        logger.info(
            f"帧率口径修正: r_frame_rate {nominal_fps:.3f} → "
            f"实测均值 {fps:.3f} (弹幕时间轴按实测值对齐)"
        )
    return VideoInfo(
        width=int(info["width"]),
        height=int(info["height"]),
        fps=fps,
        frames=frames,
        codec=codec,
    )
