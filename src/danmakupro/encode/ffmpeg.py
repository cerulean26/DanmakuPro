"""FFmpeg 编码管理器

负责构建 FFmpeg 命令行、启动进程、写入帧数据、清理资源。
"""

from __future__ import annotations

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


class FFmpegManager:
    """FFmpeg 进程管理器"""

    _SPEED_RE = re.compile(r'speed=\s*([\d.]+)x')

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
        self.active_pipeline: str = EncodeMode.CPU
        self.process: subprocess.Popen | None = None
        self.stderr_thread: threading.Thread | None = None
        self._speed_lock = threading.Lock()
        self._current_speed: float = 0.0
        self._aborted: bool = False

        self._resolve_encode_mode()

    @property
    def current_speed(self) -> float:
        """当前编码速度（相对于实时播放的倍数）。

        1.0x = 实时，2.0x = 两倍速，0.5x = 需要两倍时间。
        线程安全，可从渲染主线程读取。
        """
        with self._speed_lock:
            return self._current_speed

    def _resolve_encode_mode(self) -> None:
        """解析编码模式。"""
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "未找到 FFmpeg，请先安装:\n"
                "  Windows: winget install ffmpeg 或 scoop install ffmpeg\n"
                "  其他系统: https://ffmpeg.org/download.html"
            )

        if self.encode_mode == EncodeMode.CPU:
            self.active_pipeline = EncodeMode.CPU
            logger.info("编码模式: CPU (libx264)")
            return

        if self.encode_mode == EncodeMode.GPU:
            if not self._check_nvenc_available():
                raise RuntimeError("未检测到 NVENC 编码器")
            self.active_pipeline = EncodeMode.GPU
            logger.info("编码模式: GPU (NVENC)")
            return

        if self.encode_mode == EncodeMode.QSV:
            if not self._check_qsv_available():
                raise RuntimeError("未检测到 QSV 编码器")
            self.active_pipeline = EncodeMode.QSV
            logger.info("编码模式: QSV")
            return

        if self._check_nvenc_available():
            self.active_pipeline = EncodeMode.GPU
            logger.info("编码模式: GPU (NVENC) — 自动检测")
            return

        if self._check_qsv_available():
            self.active_pipeline = EncodeMode.QSV
            logger.info("编码模式: QSV — 自动回退")
            return

        self.active_pipeline = EncodeMode.CPU
        logger.info("编码模式: CPU (libx264) — 自动回退")

    @staticmethod
    def _check_nvenc_available() -> bool:
        """检查 NVENC 是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10,
            )
            if "h264_nvenc" not in result.stdout:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner",
                    "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                    "-c:v", "h264_nvenc", "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _check_qsv_available() -> bool:
        """检查 QSV 是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10,
            )
            if "h264_qsv" not in result.stdout:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner",
                    "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                    "-c:v", "h264_qsv", "-f", "null", "-",
                ],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_video_info(self) -> dict[str, int | float]:
        """获取视频元数据"""
        if shutil.which("ffprobe") is None:
            raise RuntimeError(
                "未找到 ffprobe，请先安装 FFmpeg:\n"
                "  Windows: winget install ffmpeg 或 scoop install ffmpeg\n"
                "  其他系统: https://ffmpeg.org/download.html"
            )
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames:format=duration",
            "-of", "json", self.video_in,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        info = data["streams"][0]
        num, den = map(int, info["r_frame_rate"].split('/'))
        fps = num / den
        frames = int(info.get("nb_frames", 0))

        if frames == 0:
            dur = float(data["format"]["duration"])
            frames = int(dur * fps)

        return {"w": int(info["width"]), "h": int(info["height"]), "fps": fps, "frames": frames}

    def build_command(self, fps: float, w: int, h: int, layer_params: LayerParams) -> list[str]:
        """构建 FFmpeg 命令"""
        if self.active_pipeline == EncodeMode.GPU:
            return self._build_gpu_command(fps, w, h, layer_params)
        if self.active_pipeline == EncodeMode.QSV:
            return self._build_qsv_command(fps, w, h, layer_params)
        return self._build_cpu_command(fps, w, h, layer_params)

    def _build_gpu_command(self, fps: float, w: int, h: int, lp: LayerParams) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda",
            "-c:v", "h264_cuvid",
            "-i", self.video_in,
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{lp.layer_w}x{lp.layer_h}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-filter_complex",
            (
                f"[0:v]scale_cuda=w={w}:h={h}:format=yuv420p:interp_algo=lanczos,"
                f"hwdownload,format=yuv420p[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "h264_nvenc",
            "-preset", self.encode_params.gpu_preset,
            "-cq:v", str(self.encode_params.gpu_cq),
            "-rc:v", "constqp",
            "-c:a", "copy",
            self.video_out,
        ]

    def _build_qsv_command(self, fps: float, w: int, h: int, lp: LayerParams) -> list[str]:
        return [
            "ffmpeg", "-y",
            "-hwaccel", "qsv",
            "-c:v", "h264_qsv",
            "-i", self.video_in,
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{lp.layer_w}x{lp.layer_h}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-filter_complex",
            (
                f"[0:v]scale_qsv=w={w}:h={h}:mode=hq[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "h264_qsv",
            "-preset", self.encode_params.qsv_preset,
            "-global_quality", str(self.encode_params.qsv_quality),
            "-c:a", "copy",
            self.video_out,
        ]

    def _build_cpu_command(self, fps: float, w: int, h: int, lp: LayerParams) -> list[str]:
        cpu_count = os.cpu_count() or 4
        encode_threads = max(1, cpu_count - self.encode_params.cpu_min_reserve_threads)

        return [
            "ffmpeg", "-y",
            "-i", self.video_in,
            "-f", "rawvideo",
            "-pix_fmt", "bgra",
            "-s", f"{lp.layer_w}x{lp.layer_h}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-filter_complex",
            (
                f"[0:v]scale={w}:{h}:flags=lanczos[bg];"
                f"[1:v]format=yuva420p[fg];"
                f"[bg][fg]overlay=x={lp.layer_x}:y={lp.layer_y}[out]"
            ),
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", self.encode_params.cpu_preset,
            "-crf", str(self.encode_params.cpu_crf),
            "-threads", str(encode_threads),
            "-c:a", "copy",
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
                proc.stderr, encoding="utf-8", errors="replace",
            )
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

    def abort(self) -> None:
        """标记为已中断，cleanup 时将直接终止进程而非等待完成"""
        self._aborted = True

    def close_stdin(self) -> None:
        """关闭 FFmpeg stdin，用于外部中断阻塞的写入"""
        self._aborted = True
        if self.process and self.process.stdin:
            try:
                self.process.stdin.close()
            except (OSError, BrokenPipeError):
                pass

    def cleanup(self) -> None:
        """清理资源。

        按顺序完成：
        1. 关闭 stdin 管道，通知 FFmpeg 输入结束
        2. 等待 stderr 线程结束（避免日志丢失）
        3. 等待 FFmpeg 进程退出（或被中断时直接 kill）
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

        # 第三步：处理进程退出
        if self._aborted:
            try:
                proc.kill()
                proc.wait(timeout=5.0)
            except Exception:
                pass
        else:
            try:
                return_code = proc.wait(timeout=600.0)
                if return_code == 0:
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