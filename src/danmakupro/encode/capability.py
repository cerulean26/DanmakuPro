"""FFmpeg 硬件能力探测

回答两个问题：本机 ffmpeg 有没有某个硬件编码器、能不能硬解某份输入。
两者都只取决于 ffmpeg 安装与硬件，故探测结果带进程级缓存。
"""

from __future__ import annotations

import functools
import re
import subprocess

from loguru import logger

from ..config.models import EncodeMode
from .probe import run_probe

# 编码模式 → (管线类型, ffmpeg 编码器名, 不可用时的 CPU 回退模式)。
_MODE_CONFIG: dict[str, tuple[str, str, str]] = {
    EncodeMode.H264: ("cpu", "libx264", EncodeMode.H264),
    EncodeMode.H264_NVENC: ("gpu", "h264_nvenc", EncodeMode.H264),
    EncodeMode.H264_QSV: ("qsv", "h264_qsv", EncodeMode.H264),
    EncodeMode.H265: ("cpu", "libx265", EncodeMode.H265),
    EncodeMode.H265_NVENC: ("gpu", "hevc_nvenc", EncodeMode.H265),
    EncodeMode.H265_QSV: ("qsv", "hevc_qsv", EncodeMode.H265),
    EncodeMode.AV1: ("cpu", "libsvtav1", EncodeMode.AV1),
    EncodeMode.AV1_NVENC: ("gpu", "av1_nvenc", EncodeMode.AV1),
    EncodeMode.AV1_QSV: ("qsv", "av1_qsv", EncodeMode.AV1),
}


# 编码模式 → 管线类型。
def pipeline_kind(mode: str) -> str:
    """返回编码模式对应的管线类型：cpu / gpu / qsv。"""
    return _MODE_CONFIG[mode][0]


# 编码模式 → ffmpeg 编码器名。
def encoder_for_mode(mode: str) -> str:
    """返回编码模式对应的 ffmpeg 编码器名。"""
    return _MODE_CONFIG[mode][1]


# 编码模式 → 不可用时的 CPU 回退模式。
def fallback_cpu_mode(mode: str) -> str:
    """返回硬件管线不可用时的 CPU 回退模式。"""
    return _MODE_CONFIG[mode][2]


# 编码模式 → 用户可读名称。
def pipeline_label(mode: str) -> str:
    """编码模式的用户可读名称。"""
    labels: dict[str, str] = {
        EncodeMode.H264: "CPU (libx264)",
        EncodeMode.H264_NVENC: "GPU (NVENC H.264)",
        EncodeMode.H264_QSV: "QSV (H.264)",
        EncodeMode.H265: "CPU (libx265)",
        EncodeMode.H265_NVENC: "GPU (NVENC H.265)",
        EncodeMode.H265_QSV: "QSV (H.265)",
        EncodeMode.AV1: "CPU (libsvtav1)",
        EncodeMode.AV1_NVENC: "GPU (NVENC AV1)",
        EncodeMode.AV1_QSV: "QSV (AV1)",
    }
    return labels.get(mode, mode)


#: 管线类型 → ffmpeg -hwaccel 方式。
HWACCEL_METHOD: dict[str, str] = {
    "gpu": "cuda",
    "qsv": "qsv",
}


#: 管线类型 → 报错文案中对编码器的称呼。
HW_ENCODER_LABELS: dict[str, str] = {
    "gpu": "NVENC",
    "qsv": "QSV",
}

#: 解析 ffmpeg -decoders 行尾 (codec xxx)，与 ffprobe codec_name 同源对齐。
_DECODER_LINE_RE = re.compile(r"^\s*V.{5}\s+(\S+)\s+.*\(codec (\S+)\)\s*$")


def probe_encoder_available(encoder: str, timeout: int) -> bool:
    """探测编码器是否可用：先查 -encoders 列表，再用 lavfi 空源试编验证驱动可用。"""
    try:
        result = run_probe(
            ["ffmpeg", "-hide_banner", "-encoders"], timeout, check=False
        )
        if encoder not in result.stdout:
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    try:
        result = run_probe(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=64x64:d=0.1",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            timeout,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@functools.lru_cache(maxsize=None)
def hardware_decodable_codecs(
    hwaccel: str, ffmpeg_exe: str, timeout: int
) -> frozenset[str] | None:
    """该 ffmpeg 构建中能用 hwaccel 硬解的编码集合，探测失败返回 None。

    解析 -decoders 中的 *_cuvid / *_qsv 条目作为硬解代理，与 ffprobe codec_name 对齐。
    详细依据见 ADR-0002。
    """
    suffix = {"cuda": "_cuvid", "qsv": "_qsv"}.get(hwaccel)
    if suffix is None:
        return None
    try:
        result = run_probe([ffmpeg_exe, "-hide_banner", "-decoders"], timeout)
    except (subprocess.SubprocessError, OSError, TypeError):
        return None

    codecs = set()
    for line in result.stdout.splitlines():
        matched = _DECODER_LINE_RE.match(line)
        if matched and matched.group(1).endswith(suffix):
            codecs.add(matched.group(2))
    return frozenset(codecs)


def can_hw_decode(
    kind: str, ffmpeg_exe: str, timeout: int, input_codec: str | None
) -> bool:
    """硬件管线能否硬解这份输入。输入编码未知或探测失败时按 True 处理（不误降级）。"""
    if input_codec is None:
        return True
    supported = hardware_decodable_codecs(HWACCEL_METHOD[kind], ffmpeg_exe, timeout)
    if supported is None:
        return True
    return input_codec in supported


def warn_hw_downgrade(mode: str, input_codec: str | None) -> None:
    """提示因无硬解而从硬件管线回落到 CPU。"""
    logger.warning(
        f"输入编码 {input_codec} 无 {pipeline_label(mode)} 硬解，"
        "本次改用 CPU 管线压制（画面与参数设置不变，仅速度较慢）"
    )
