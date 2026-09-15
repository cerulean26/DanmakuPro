"""FFmpeg 编码管理器

负责构建 FFmpeg 命令行、启动进程、写入帧数据、清理资源。
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import threading
from io import TextIOWrapper

from loguru import logger

from ..config.models import EncodeMode, EncodeParams, SystemParams, DEFAULT_CONFIG
from ..layout.params import LayerParams

#: 探测子进程允许的最小超时（秒），防止用户把 ffmpeg_timeout 配得过小导致误判
_PROBE_TIMEOUT_MIN = 1

#: 帧率口径修正达到多大相对偏差才值得提示。CFR 素材的容器舍入通常只有
#: 万分之几（实测 source/5.flv：22.000 → 21.999），逐条打印纯属噪音。
_FPS_LOG_TOLERANCE = 0.005

_PIPELINE_LABELS: dict[str, str] = {
    EncodeMode.GPU: "GPU (NVENC)",
    EncodeMode.QSV: "QSV",
    EncodeMode.CPU: "CPU (libx264)",
}


class FFmpegManager:
    """FFmpeg 进程管理器"""

    _SPEED_RE = re.compile(r"speed=\s*([\d.]+)x")

    #: VFR 采样判据：在视频前、中、后各取 _VFR_SAMPLE_SECONDS 秒，比较三段
    #: 局部帧率的相对极差，超过 _VFR_SAMPLE_TOLERANCE 即判为变帧率。
    #:
    #: 不使用 r_frame_rate 与 avg_frame_rate 比对：FLV 的 avg_frame_rate 取自
    #: onMetaData，实测 source/1.flv 标 22/1、真实 19.985fps，会误报。2% 足以
    #: 区分容器时间戳舍入（实测本项目产物 0.1%）与真正的帧率波动。
    _VFR_SAMPLE_TOLERANCE = 0.02
    _VFR_SAMPLE_SECONDS = 5.0

    #: 帧率口径修正的可信区间：frames/duration 与 r_frame_rate 的比值超出该
    #: 范围，说明 nb_frames 或 duration 本身不可信，回落到 r_frame_rate。
    _FPS_SANITY_LO = 1 / 3
    _FPS_SANITY_HI = 3.0

    def __init__(
        self,
        video_in: str,
        video_out: str,
        encode_mode: str = EncodeMode.AUTO,
        encode_params: EncodeParams = DEFAULT_CONFIG.encode,
        system_params: SystemParams = DEFAULT_CONFIG.system,
    ):
        self.video_in = video_in
        self.video_out = video_out
        self.encode_mode = encode_mode
        self.encode_params = encode_params
        self.system_params = system_params
        #: FFmpeg 是否以 returncode 0 正常收尾。压制失败时调用方据此清理残缺产物。
        self.encode_succeeded: bool = False
        #: 本次压制是否被用户中断（Ctrl+C）。中断时 FFmpeg 收到 stdin EOF 后仍会
        #: 以 0 退出，只看 returncode 会误报「压制完成」，故需单独标记。
        self.interrupted: bool = False
        self.process: subprocess.Popen | None = None
        self.stderr_thread: threading.Thread | None = None
        self._speed_lock = threading.Lock()
        self._current_speed: float = 0.0
        #: 编码管线（gpu / qsv / cpu）。**惰性解析** —— 构造时不起子进程探测
        #: （auto 模式首次约 1.5s），首次读取 active_pipeline 时才探测。
        #: 这样「只构造不使用」的场景（GUI 建好对象后用户取消、单测只断言
        #: 构造参数）不必白付探测代价。取值请走 active_pipeline 属性。
        self._active_pipeline: str | None = None

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
        """当前生效的编码管线（gpu / qsv / cpu）。

        首次访问时才解析：探测要起 ffmpeg 子进程（缓存未命中时约 1.5s），
        构造对象本身不该承担这份代价。解析一次后缓存在实例上。
        """
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
            解析出的管线（EncodeMode.GPU / EncodeMode.QSV / EncodeMode.CPU）。

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

        timeout = max(_PROBE_TIMEOUT_MIN, self.system_params.ffmpeg_timeout)
        resolved = _probe_encode_pipeline(str(self.encode_mode), ffmpeg_exe, timeout)
        self._active_pipeline = resolved

        label = _PIPELINE_LABELS[resolved]
        if self.encode_mode == EncodeMode.AUTO:
            label += " — 自动检测" if resolved == EncodeMode.GPU else " — 自动回退"
        logger.info(f"编码模式: {label}")
        return resolved

    @staticmethod
    def clear_probe_cache() -> None:
        """清空编码器探测缓存。

        硬件或 ffmpeg 安装发生变化（如插入 eGPU、重装 ffmpeg）后调用，
        否则进程内会一直复用首次探测的结果。测试中亦用于保证用例隔离。
        """
        _probe_encode_pipeline.cache_clear()

    @staticmethod
    def _check_nvenc_available(
        timeout: int = DEFAULT_CONFIG.system.ffmpeg_timeout,
    ) -> bool:
        """检查 NVENC 是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if "h264_nvenc" not in result.stdout:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-f",
                    "lavfi",
                    "-i",
                    "nullsrc=s=64x64:d=0.1",
                    "-c:v",
                    "h264_nvenc",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _check_qsv_available(
        timeout: int = DEFAULT_CONFIG.system.ffmpeg_timeout,
    ) -> bool:
        """检查 QSV 是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if "h264_qsv" not in result.stdout:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-f",
                    "lavfi",
                    "-i",
                    "nullsrc=s=64x64:d=0.1",
                    "-c:v",
                    "h264_qsv",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _parse_frame_rate(raw: str | None) -> float:
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

    @staticmethod
    def _resolve_render_fps(nominal_fps: float, frames: int, duration: float) -> float:
        """确定渲染用的帧率。

        渲染循环按 frame_index / fps 推算弹幕时间，故弹幕层时间轴长度为
        frames / fps，它必须等于视频真实时长：短了则弹幕层提前耗尽，画面继续
        播放而弹幕冻结在最后一帧；长了则画面播完仍在输出弹幕。

        r_frame_rate 只是容器标称值，VFR 源上会明显偏离真实均值（例如标称
        30fps、真实平均 20fps 时，时间轴只有实际时长的 2/3，尾部弹幕全丢），
        因此只要 frames 与 duration 可用且二者之比可信，就以 frames/duration
        为准。这样弹幕时间轴天然等于时长，无需改动视频流本身。

        Args:
            nominal_fps: r_frame_rate 的解析结果
            frames: 总帧数
            duration: 真实时长（秒），不可用时为 0

        Returns:
            渲染帧率；输入不足或比值离谱时回落到 nominal_fps。
        """
        if nominal_fps <= 0 or frames <= 0 or duration <= 0:
            return nominal_fps
        real_fps = frames / duration
        if real_fps <= 0:
            return nominal_fps
        ratio = real_fps / nominal_fps
        if not (FFmpegManager._FPS_SANITY_LO <= ratio <= FFmpegManager._FPS_SANITY_HI):
            return nominal_fps
        return real_fps

    @staticmethod
    def _detect_vfr(local_rates: list[float]) -> bool:
        """根据各采样段的局部帧率判断是否变帧率。

        Args:
            local_rates: _sample_local_frame_rates 的返回值

        Returns:
            采样段不足时返回 False（无法判定时不误报）。
        """
        if len(local_rates) < 2:
            return False
        lo = min(local_rates)
        hi = max(local_rates)
        return lo > 0 and (hi - lo) / lo > FFmpegManager._VFR_SAMPLE_TOLERANCE

    def _sample_local_frame_rates(self, duration: float) -> list[float]:
        """在视频前、中、后各采样一段，返回各段的局部帧率（fps）。

        Args:
            duration: 视频总时长（秒）

        Returns:
            各采样段的局部帧率。无法采样或样本不足时返回空列表，
            调用方据此按「无法判定」处理而不是误报 VFR。
        """
        # 短片没必要采样：三段加起来就接近全片，且 seek 误差占比过高。
        if duration < self._VFR_SAMPLE_SECONDS * 3:
            return []
        starts = (
            0.0,
            duration / 2,
            max(0.0, duration - self._VFR_SAMPLE_SECONDS),
        )
        timeout = max(_PROBE_TIMEOUT_MIN, self.system_params.ffmpeg_timeout)
        rates: list[float] = []
        for start in starts:
            spec = f"{start:.3f}%+" + f"{self._VFR_SAMPLE_SECONDS:.3f}"
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-read_intervals",
                spec,
                "-show_entries",
                "frame=pts_time",
                "-of",
                "json",
                self.video_in,
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=timeout,
                )
                raw = json.loads(result.stdout).get("frames", [])
            except (subprocess.SubprocessError, OSError, ValueError):
                return []
            pts: list[float] = []
            for item in raw:
                try:
                    pts.append(float(item["pts_time"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if len(pts) < 2:
                return []
            span = pts[-1] - pts[0]
            if span <= 0:
                return []
            rates.append((len(pts) - 1) / span)
        return rates

    def get_video_info(self) -> dict[str, int | float | bool]:
        """获取视频元数据。

        Returns:
            w / h / fps / frames 四个基本字段，外加 vfr 标记。

            fps 是**渲染用**帧率，可能不等于 r_frame_rate：当 nb_frames 与
            duration 可用时取 frames / duration，以保证弹幕时间轴长度等于
            视频真实时长（详见 _resolve_render_fps）。

            vfr 为 True 表示采样发现全片帧率不恒定。弹幕时间轴已按真实平均
            帧率对齐，不会漂移，但画面帧率波动时弹幕运动会略有顿挫。
        """
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
            "stream=width,height,r_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            self.video_in,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=self.system_params.ffmpeg_timeout,
        )
        data = json.loads(result.stdout)
        info = data["streams"][0]
        nominal_fps = FFmpegManager._parse_frame_rate(info.get("r_frame_rate"))

        # nb_frames 在 flv/mp4 上可能缺失或为 "N/A"，不能无条件 int()。
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
            frames = int(duration * nominal_fps)

        fps = FFmpegManager._resolve_render_fps(nominal_fps, frames, duration)
        if (
            nominal_fps > 0
            and abs(fps - nominal_fps) / nominal_fps > _FPS_LOG_TOLERANCE
        ):
            logger.info(
                f"帧率口径修正: r_frame_rate {nominal_fps:.3f} → "
                f"实测均值 {fps:.3f} (弹幕时间轴按实测值对齐)"
            )
        vfr = FFmpegManager._detect_vfr(self._sample_local_frame_rates(duration))

        return {
            "w": int(info["width"]),
            "h": int(info["height"]),
            "fps": fps,
            "frames": frames,
            "vfr": vfr,
        }

    def build_command(
        self, fps: float, w: int, h: int, layer_params: LayerParams
    ) -> list[str]:
        """构建 FFmpeg 命令"""
        if self.active_pipeline == EncodeMode.GPU:
            return self._build_gpu_command(fps, w, h, layer_params)
        if self.active_pipeline == EncodeMode.QSV:
            return self._build_qsv_command(fps, w, h, layer_params)
        return self._build_cpu_command(fps, w, h, layer_params)

    def _build_gpu_command(
        self, fps: float, w: int, h: int, lp: LayerParams
    ) -> list[str]:
        return [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "cuda",
            "-hwaccel_output_format",
            "cuda",
            "-c:v",
            "h264_cuvid",
            "-i",
            self.video_in,
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
                f"[0:v]scale_cuda=w={w}:h={h}:format=yuv420p:interp_algo=lanczos,"
                f"hwdownload,format=yuv420p[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map",
            "[out]",
            "-map",
            "0:a?",
            "-c:v",
            "h264_nvenc",
            "-preset",
            self.encode_params.gpu_preset,
            "-cq:v",
            str(self.encode_params.gpu_cq),
            "-rc:v",
            "constqp",
            "-c:a",
            "copy",
            self.video_out,
        ]

    def _build_qsv_command(
        self, fps: float, w: int, h: int, lp: LayerParams
    ) -> list[str]:
        return [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "qsv",
            "-hwaccel_output_format",
            "qsv",
            "-c:v",
            "h264_qsv",
            "-i",
            self.video_in,
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
                f"[0:v]hwdownload,format=nv12,"
                f"scale={w}:{h}:flags=lanczos,format=yuv420p[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map",
            "[out]",
            "-map",
            "0:a?",
            "-c:v",
            "h264_qsv",
            "-preset",
            self.encode_params.qsv_preset,
            "-global_quality",
            str(self.encode_params.qsv_quality),
            "-c:a",
            "copy",
            self.video_out,
        ]

    def _build_cpu_command(
        self, fps: float, w: int, h: int, lp: LayerParams
    ) -> list[str]:
        cpu_count = os.cpu_count() or 4
        encode_threads = max(1, cpu_count - self.encode_params.cpu_min_reserve_threads)

        return [
            "ffmpeg",
            "-y",
            "-i",
            self.video_in,
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
                f"[0:v]scale={w}:{h}:flags=lanczos[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map",
            "[out]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            self.encode_params.cpu_preset,
            "-crf",
            str(self.encode_params.cpu_crf),
            "-threads",
            str(encode_threads),
            "-c:a",
            "copy",
            self.video_out,
        ]

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
        """清理资源。

        按顺序完成：
        1. 关闭 stdin 管道，通知 FFmpeg 输入结束
        2. 等待 stderr 线程结束（避免日志丢失）
        3. 等待 FFmpeg 进程退出
        4. 关闭 stderr 管道，释放资源
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
                # 中断时 FFmpeg 有两种死法：控制台 Ctrl+C 会连带杀掉它
                # （Windows 实测 code=255），只在 Python 侧中断则它按
                # stdin EOF 正常收尾（code=0）。两者都不是「成功」也不是
                # 「失败」，输出同样残缺，故统一按中断记，不用 ERROR。
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
# 模块级辅助函数
# =============================================================================


@functools.lru_cache(maxsize=None)
def _probe_encode_pipeline(encode_mode: str, ffmpeg_exe: str, timeout: int) -> str:
    """探测实际可用的编码管线（带进程级缓存）。

    编码器探测要启动 2~4 个 ffmpeg 子进程，实测耗时 auto 1.03s / gpu 1.45s /
    qsv 2.63s（cpu 无需探测，0.04s）。结果只取决于 ffmpeg 安装与硬件，
    因此在一个进程内缓存即可 —— 否则每次构造 FFmpegManager 都要重付一遍。

    Args:
        encode_mode: 用户请求的编码模式
        ffmpeg_exe: ffmpeg 可执行文件路径（参与缓存 key，换 ffmpeg 即失效）
        timeout: 单次探测子进程的超时秒数

    Returns:
        EncodeMode 中实际可用的管线

    Raises:
        RuntimeError: 显式指定 gpu/qsv 但对应编码器不可用
    """
    if encode_mode == EncodeMode.CPU:
        return EncodeMode.CPU

    if encode_mode == EncodeMode.GPU:
        if not FFmpegManager._check_nvenc_available(timeout):
            raise RuntimeError("未检测到 NVENC 编码器")
        return EncodeMode.GPU

    if encode_mode == EncodeMode.QSV:
        if not FFmpegManager._check_qsv_available(timeout):
            raise RuntimeError("未检测到 QSV 编码器")
        return EncodeMode.QSV

    # AUTO：优先 NVENC，其次 QSV，最后回退 CPU
    if FFmpegManager._check_nvenc_available(timeout):
        return EncodeMode.GPU
    if FFmpegManager._check_qsv_available(timeout):
        return EncodeMode.QSV
    return EncodeMode.CPU
