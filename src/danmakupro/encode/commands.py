"""FFmpeg 命令行构建

三条管线（NVENC / QSV / CPU）的命令行只有三处不同：输入侧的 -hwaccel、把画面
缩放成 [bg] 的链条、输出侧的编码器参数；弹幕层输入、overlay 合成、-map 与音轨
复制逐字相同，由 _assemble_command 统一拼装。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..config.models import EncodeParams
from ..layout.params import LayerParams
from .capability import pipeline_kind, encoder_for_mode


@dataclass(frozen=True)
class CommandInputs:
    """构建命令行所需的实例侧输入。

    Attributes:
        video_in: 输入视频路径
        video_out: 输出视频路径
        encode_params: 编码参数，决定预设、质量与线程数
    """

    video_in: str
    video_out: str
    encode_params: EncodeParams


def build_command(
    pipeline: str,
    inputs: CommandInputs,
    fps: float,
    w: int,
    h: int,
    lp: LayerParams,
) -> list[str]:
    """按管线构建 FFmpeg 命令行。

    Args:
        pipeline: EncodeMode 值（如 h264_nvenc），决定管线类型与编码器
        inputs: 输入输出路径与编码参数
        fps: 弹幕层帧率，须与渲染帧率一致（口径见 encode.probe.resolve_render_fps）
        w: 输出宽度（缩放到该尺寸，可能是裁切后的画面尺寸）
        h: 输出高度
        lp: 弹幕层布局参数

    Returns:
        可直接交给 subprocess 的命令行参数列表。
    """
    kind = pipeline_kind(pipeline)
    encoder = encoder_for_mode(pipeline)
    if kind == "gpu":
        return _build_gpu_command(inputs, fps, w, h, lp, encoder)
    if kind == "qsv":
        return _build_qsv_command(inputs, fps, w, h, lp, encoder)
    return _build_cpu_command(inputs, fps, w, h, lp, encoder)


def _assemble_command(
    inputs: CommandInputs,
    fps: float,
    lp: LayerParams,
    *,
    hwaccel: list[str],
    background: str,
    encoder: list[str],
) -> list[str]:
    """按管线共用的骨架拼装 FFmpeg 命令行。

    Args:
        inputs: 输入输出路径与编码参数
        fps: 弹幕层帧率，须与渲染帧率一致
        lp: 弹幕层布局参数，决定弹幕层的尺寸与叠加位置
        hwaccel: 输入侧 -hwaccel 参数；CPU 管线传空列表
        background: 产出 [bg] 标签的画面缩放链（各管线不同，不含标签本身）
        encoder: 输出侧 -c:v 及其编码参数

    Returns:
        可直接交给 subprocess 的命令行参数列表。
    """
    return [
        "ffmpeg",
        "-y",
        *hwaccel,
        "-i",
        inputs.video_in,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-s",
        f"{lp.layer_w}x{lp.layer_h}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-filter_complex",
        (
            f"{background}[bg];"
            f"[1:v]format=yuva420p[fg];"
            f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
        ),
        "-map",
        "[out]",
        "-map",
        "0:a?",
        *encoder,
        "-c:a",
        "copy",
        inputs.video_out,
    ]


def _build_gpu_command(
    inputs: CommandInputs, fps: float, w: int, h: int, lp: LayerParams, encoder: str
) -> list[str]:
    """NVENC 管线：显存内 scale_cuda 缩放，再 hwdownload 下来叠加弹幕。

    不写死输入解码器，交给 ffmpeg 依据 -hwaccel cuda 自选：写死时非
    H.264 输入会在绑定 scale_cuda 前就失败。不可硬解的编码已在开跑前的
    能力探测里判掉并落到 CPU 管线。
    依据见 docs/decisions/ADR-0002-hardware-pipeline-decoder.md。
    """
    return _assemble_command(
        inputs,
        fps,
        lp,
        hwaccel=["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
        background=(
            f"[0:v]scale_cuda=w={w}:h={h}:format=yuv420p:interp_algo=lanczos,"
            "hwdownload,format=yuv420p"
        ),
        encoder=[
            "-c:v",
            encoder,
            "-preset",
            inputs.encode_params.gpu_preset,
            "-cq:v",
            str(inputs.encode_params.gpu_cq),
            "-rc:v",
            "constqp",
        ],
    )


def _build_qsv_command(
    inputs: CommandInputs, fps: float, w: int, h: int, lp: LayerParams, encoder: str
) -> list[str]:
    """QSV 管线：硬解帧下载到系统内存缩放后再叠加弹幕。

    同样不指定输入解码器，理由见 _build_gpu_command。本机 QSV 无 mpeg4
    硬解（无 mpeg4_qsv），这类输入靠开跑前的判据落到 CPU。
    """
    return _assemble_command(
        inputs,
        fps,
        lp,
        hwaccel=["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"],
        background=(
            f"[0:v]hwdownload,format=nv12,scale={w}:{h}:flags=lanczos,format=yuv420p"
        ),
        encoder=[
            "-c:v",
            encoder,
            "-preset",
            inputs.encode_params.qsv_preset,
            "-global_quality",
            str(inputs.encode_params.qsv_quality),
        ],
    )


def _build_cpu_command(
    inputs: CommandInputs, fps: float, w: int, h: int, lp: LayerParams, encoder: str
) -> list[str]:
    """CPU 管线：硬件管线不可用时的兜底。

    线程数留出 cpu_min_reserve_threads 个核，避免渲染线程被编码吃满。
    """
    encode_threads = max(
        1,
        (os.cpu_count() or 4) - inputs.encode_params.cpu_min_reserve_threads,
    )
    return _assemble_command(
        inputs,
        fps,
        lp,
        hwaccel=[],
        background=f"[0:v]scale={w}:{h}:flags=lanczos",
        encoder=[
            "-c:v",
            encoder,
            "-preset",
            inputs.encode_params.cpu_preset,
            "-crf",
            str(inputs.encode_params.cpu_crf),
            "-threads",
            str(encode_threads),
        ],
    )
