"""FFmpeg 进程管理器

编排一次压制：解析编码管线、启停 FFmpeg 子进程、写入帧数据、回收资源。
视频元数据探测见 encode.probe，硬件能力探测见 encode.capability，
命令行构建见 encode.commands。
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import threading
from io import TextIOWrapper

from loguru import logger

from ..config.models import EncodeMode, EncodeParams, SystemParams, DEFAULT_CONFIG
from ..layout.params import LayerParams
from . import probe
from .capability import (
    HW_ENCODER_LABELS,
    can_hw_decode,
    encoder_for_mode,
    fallback_cpu_mode,
    hardware_decodable_codecs,
    pipeline_kind,
    pipeline_label,
    probe_encoder_available,
    warn_hw_downgrade,
)
from .commands import CommandInputs, build_command


class FFmpegManager:
    """FFmpeg 进程管理器"""

    _SPEED_RE = re.compile(r"speed=\s*([\d.]+)x")

    def __init__(
        self,
        video_in: str,
        video_out: str,
        encode_mode: str = EncodeMode.H264,
        encode_params: EncodeParams = DEFAULT_CONFIG.encode,
        system_params: SystemParams = DEFAULT_CONFIG.system,
    ):
        self.video_in = video_in
        self.video_out = video_out
        self.encode_mode = encode_mode
        self.encode_params = encode_params
        self.system_params = system_params
        #: 编码是否正常结束（returncode == 0），失败时用于清理残缺产物。
        self.encode_succeeded: bool = False
        #: 是否被用户中断；须独立于 returncode 判定（中断后 FFmpeg 仍可能返回 0）。
        self.interrupted: bool = False
        self.process: subprocess.Popen | None = None
        self.stderr_thread: threading.Thread | None = None
        self._speed_lock = threading.Lock()
        self._current_speed: float = 0.0
        #: 编码管线，惰性探测，通过 active_pipeline 属性访问。
        self._active_pipeline: str | None = None
        #: 输入视频编码格式，硬解兼容性判据（由 get_video_info 回填）。
        self._input_codec: str | None = None

    @property
    def current_speed(self) -> float:
        """当前编码速度（相对于实时播放的倍数）。

        1.0x = 实时，2.0x = 两倍速，0.5x = 需要两倍时间。
        线程安全，可从渲染主线程读取。
        """
        with self._speed_lock:
            return self._current_speed

    @property
    def active_pipeline(self) -> str:
        """当前生效的编码管线（gpu / qsv / cpu），首次访问时惰性探测并缓存。"""
        if self._active_pipeline is None:
            return self._resolve_encode_mode()
        return self._active_pipeline

    @active_pipeline.setter
    def active_pipeline(self, value: str) -> None:
        """显式指定编码管线，跳过探测。

        供测试替身与「已知目标环境」的部署使用。正常流程不应调用，
        否则会绕过 NVENC / QSV 的可用性检查。
        """
        self._active_pipeline = value

    def _resolve_encode_mode(self) -> str:
        """解析编码模式并记录到 _active_pipeline。

        探测结果按 (编码模式, ffmpeg 路径, 超时) 做进程级缓存，重复构造
        FFmpegManager（例如 GUI 中反复点击「开始压制」）不会重跑子进程。
        本方法由 active_pipeline 的 getter 在首次访问时调用，也可显式调用。

        Returns:
            解析出的 EncodeMode 值。

        Raises:
            RuntimeError: 未找到 ffmpeg，或指定模式对应的编码器不可用。
        """
        ffmpeg_exe = shutil.which("ffmpeg")
        if ffmpeg_exe is None:
            raise RuntimeError(
                "未找到 FFmpeg，请先安装:\n"
                "  Windows: winget install ffmpeg 或 scoop install ffmpeg\n"
                "  其他系统: https://ffmpeg.org/download.html"
            )

        timeout = max(probe.PROBE_TIMEOUT_MIN, self.system_params.ffmpeg_timeout)
        kind = pipeline_kind(self.encode_mode)
        input_codec = None if kind == "cpu" else self.probe_input_codec()
        resolved = _probe_encode_pipeline(
            self.encode_mode, ffmpeg_exe, timeout, input_codec
        )
        self._active_pipeline = resolved

        logger.info(f"编码模式: {pipeline_label(resolved)}")
        return resolved

    @staticmethod
    def clear_probe_cache() -> None:
        """清空编码器探测缓存。

        硬件或 ffmpeg 安装发生变化（如插入 eGPU、重装 ffmpeg）后调用，
        否则进程内会一直复用首次探测的结果。测试中亦用于保证用例隔离。
        """
        _probe_encode_pipeline.cache_clear()
        hardware_decodable_codecs.cache_clear()
        probe.probe_input_codec.cache_clear()

    def probe_input_codec(self) -> str | None:
        """探测输入视频的编码格式（ffprobe 的 codec_name），失败返回 None。

        结果在实例与进程两级缓存：同一份输入的硬解判据不会被反复起子进程，
        get_video_info() 也会顺手回填这份缓存。
        """
        if self._input_codec is not None:
            return self._input_codec
        codec = probe.probe_input_codec(
            self.video_in,
            max(probe.PROBE_TIMEOUT_MIN, self.system_params.ffmpeg_timeout),
        )
        self._input_codec = codec or None
        return self._input_codec

    def get_video_info(self) -> dict[str, int | float]:
        """获取视频元数据，返回 {w, h, fps, frames}。

        fps 为渲染用帧率（可能不等于 r_frame_rate，见 probe.resolve_render_fps）。
        """
        info = probe.read_video_info(self.video_in, self.system_params.ffmpeg_timeout)
        # 顺手回填编码格式：硬解判据与 get_video_info 都要它，顺便宜撮合一处，
        # 免得同一次压制为同一份输入起两遍 ffprobe。
        self._input_codec = info.codec
        return {
            "w": info.width,
            "h": info.height,
            "fps": info.fps,
            "frames": info.frames,
        }

    def build_command(
        self, fps: float, w: int, h: int, layer_params: LayerParams
    ) -> list[str]:
        """构建 FFmpeg 命令行，管线取当前生效的 active_pipeline。

        Args:
            fps: 弹幕层帧率，须与渲染帧率一致
            w: 输出宽度
            h: 输出高度
            layer_params: 弹幕层布局参数

        Returns:
            可直接交给 subprocess 的命令行参数列表。
        """
        return build_command(
            self.active_pipeline,
            CommandInputs(self.video_in, self.video_out, self.encode_params),
            fps,
            w,
            h,
            layer_params,
        )

    def start(self, ffmpeg_cmd: list[str]) -> None:
        """启动 FFmpeg 进程"""
        self.process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self.system_params.pipe_buffer_size,
        )

        def _read_stderr():
            proc = self.process
            if proc is None or proc.stderr is None:
                return
            stderr_text = TextIOWrapper(
                proc.stderr,
                encoding="utf-8",
                errors="replace",
            )
            try:
                for line in stderr_text:
                    line_str = line.rstrip("\n\r")
                    if not line_str:
                        continue
                    if line_str.startswith("frame="):
                        m = FFmpegManager._SPEED_RE.search(line_str)
                        if m:
                            with self._speed_lock:
                                self._current_speed = float(m.group(1))
                        continue
                    lower = line_str.lower()
                    if "error" in lower:
                        logger.error(line_str)
                    elif "warning" in lower:
                        logger.warning(line_str)
                    else:
                        logger.debug(line_str)
            except (ValueError, OSError):
                # cleanup() 可能先行关闭了管道（join 超时后继续收尾），
                # 此时读取抛 ValueError/OSError 属正常竞态，静默结束即可。
                return
            finally:
                try:
                    # 分离缓冲区：TextIOWrapper 析构时会关闭底层流，
                    # 那会销毁 cleanup() 还要用到的 proc.stderr。
                    stderr_text.detach()
                except (ValueError, OSError):
                    pass

        self.stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        self.stderr_thread.start()

    def _health_check(self) -> bool:
        """检查 FFmpeg 进程是否存活"""
        if self.process is None:
            return False
        if self.process.poll() is not None:
            logger.error(f"FFmpeg 异常退出 (code={self.process.returncode})")
            return False
        return True

    def submit_frame(self, data: memoryview) -> None:
        """提交一帧数据（同步写入 FFmpeg stdin）。

        Args:
            data: 帧像素数据的 memoryview 视图

        Raises:
            RuntimeError: FFmpeg 进程已死亡
            BrokenPipeError: FFmpeg 管道断开
        """
        if not self._health_check():
            raise RuntimeError("FFmpeg 进程已死亡")

        if self.process is None or self.process.stdin is None:
            raise RuntimeError("FFmpeg 未启动")

        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise BrokenPipeError(f"FFmpeg 管道断开: {e}") from e

    def cleanup(self) -> None:
        """收尾压制进程：通知 FFmpeg 输入结束，等待其退出并回收管道资源。

        成功、失败与中断三条路径都会调用，故不抛出异常；编码超时（600s）会
        强制终止子进程。收尾后将 process 置 None，可重复调用。
        """
        proc = self.process
        if proc is None:
            return

        # 第一步：关闭 stdin，通知 FFmpeg 输入结束
        if proc.stdin:
            try:
                proc.stdin.close()
            except (OSError, BrokenPipeError):
                pass

        # 第二步：等待 stderr 线程结束，确保日志不丢失
        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=self.system_params.stderr_thread_timeout)

        # 第三步：等待 FFmpeg 进程退出
        try:
            return_code = proc.wait(timeout=600.0)
            if self.interrupted:
                # 返回码不能用于判定中断的成败（视信号是否送达子进程，可能是 0），
                # 故以 interrupted 标记为准。中断既非成功也非失败，产物同样残缺，
                # 统一按中断记录，不用 ERROR。
                # 依据见 docs/decisions/ADR-0006-interrupt-handling.md。
                logger.warning(f"编码已随中断结束 (code={return_code})，输出不完整")
            elif return_code == 0:
                self.encode_succeeded = True
                logger.success(f"压制完成: {self.video_out}")
            else:
                logger.error(f"压制失败 (code={return_code})")
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg 编码超时（600s），强制终止")
            proc.kill()
            proc.wait()

        # 第四步：关闭 stderr 管道，释放资源
        if proc.stderr:
            try:
                proc.stderr.close()
            except (OSError, BrokenPipeError):
                pass
        self.process = None


# =============================================================================
# 管线探测编排
# =============================================================================


def _check_encoder(mode: str, timeout: int) -> bool:
    """探测编码模式对应的编码器是否可用。

    编码器名由 _MODE_CONFIG 表提供，不再需要按 GPU/QSV 分两路条件分派。

    Args:
        mode: EncodeMode 值
        timeout: 单次探测子进程的超时（秒）

    Returns:
        该编码器可用时为 True。
    """
    return probe_encoder_available(encoder_for_mode(mode), timeout)


@functools.lru_cache(maxsize=None)
def _probe_encode_pipeline(
    encode_mode: str,
    ffmpeg_exe: str,
    timeout: int,
    input_codec: str | None = None,
) -> str:
    """探测实际可用的编码管线（带进程级缓存）。

    结果只取决于 ffmpeg 安装、硬件与输入编码，因此在一个进程内缓存即可；
    否则每次构造 FFmpegManager 都要重付一遍子进程开销。

    依据见 ``docs/decisions/ADR-0002-hardware-pipeline-decoder.md``。

    Args:
        encode_mode: 用户请求的编码模式（EncodeMode 任一值）
        ffmpeg_exe: ffmpeg 可执行文件路径（参与缓存 key，换 ffmpeg 即失效）
        timeout: 单次探测子进程的超时秒数
        input_codec: 输入视频的编码格式。GPU / QSV 无法硬解该编码时**回落到
            CPU**（并给出 WARNING），因为此时压制必然失败

    Returns:
        EncodeMode 值——可能是入参本身，也可能是 CPU 回退模式

    Raises:
        RuntimeError: 显式指定 gpu/qsv 但对应编码器不可用
    """
    kind = pipeline_kind(encode_mode)
    if kind == "cpu":
        return encode_mode

    if not _check_encoder(encode_mode, timeout):
        label = HW_ENCODER_LABELS.get(kind, kind)
        raise RuntimeError(f"未检测到 {label} 编码器")
    if can_hw_decode(kind, ffmpeg_exe, timeout, input_codec):
        return encode_mode
    warn_hw_downgrade(encode_mode, input_codec)

    return fallback_cpu_mode(encode_mode)