"""FFmpeg 编码管理器

负责构建 FFmpeg 命令行、启动进程、写入帧数据、清理资源。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading

from loguru import logger

from ..config.models import EncodeMode, EncodeParams, SystemParams, DEFAULT_CONFIG
from ..layout.params import LayerParams


class FFmpegManager:
    """FFmpeg 进程管理器"""

    _SENTINEL = None

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

        self._frame_queue: queue.Queue[bytes | None] | None = None
        self._writer_thread: threading.Thread | None = None
        self._writer_error: BaseException | None = None
        self._writer_error_event = threading.Event()

        # 队列大小限制（帧数），防止内存无限增长
        self._max_queue_frames: int = system_params.max_queue_frames
        self._queue_frame_size: int = 0  # 当前队列中的帧数
        self._queue_not_full = threading.Condition()

        self._resolve_encode_mode()

    def _resolve_encode_mode(self) -> None:
        """解析编码模式。所有模式均使用异步写入。"""
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
        logger.info("正在获取视频元数据...")
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

        logger.info(f"视频: {int(info['width'])}x{int(info['height'])} @ {fps:.2f}fps, {frames} 帧")
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
            assert self.process is not None
            assert self.process.stderr is not None
            for line in self.process.stderr:
                line_str = line.decode("utf-8", errors="replace").rstrip("\n\r")
                if line_str:
                    logger.debug(line_str)

        self.stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        self.stderr_thread.start()

        self._writer_error = None
        self._writer_error_event.clear()

        self._frame_queue = queue.Queue()
        self._writer_thread = threading.Thread(target=self._pipe_writer_loop, daemon=True)
        self._writer_thread.start()
        logger.info("FFmpeg 已启动（异步写入）")

    def _health_check(self) -> bool:
        """检查 FFmpeg 进程是否存活"""
        if self.process is None:
            return False
        if self.process.poll() is not None:
            logger.error(f"FFmpeg 异常退出 (code={self.process.returncode})")
            return False
        return True

    def _pipe_writer_loop(self) -> None:
        """异步写入线程"""
        assert self._frame_queue is not None
        assert self.process is not None
        assert self.process.stdin is not None

        while True:
            data = self._frame_queue.get()
            if data is self._SENTINEL:
                break
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                logger.error(f"FFmpeg 管道断开: {e}")
                self._writer_error = e
                self._writer_error_event.set()
                self._drain_queue()
                break
            finally:
                self._queue_frame_size -= 1
                with self._queue_not_full:
                    self._queue_not_full.notify()

    def _drain_queue(self) -> None:
        """清空队列"""
        if self._frame_queue is None:
            return
        dropped = 0
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        self._queue_frame_size = max(0, self._queue_frame_size - dropped)

    def submit_frame(self, data: bytes) -> bool:
        """提交一帧数据（统一使用异步写入）。"""
        if self._writer_error_event.is_set() and self._writer_error is not None:
            raise self._writer_error

        if not self._health_check():
            error = RuntimeError("FFmpeg 进程已死亡")
            self._writer_error = error
            self._writer_error_event.set()
            raise error

        if self._frame_queue is None:
            raise RuntimeError("FFmpeg 未启动")
        # 限制队列大小，防止内存无限增长
        with self._queue_not_full:
            while self._queue_frame_size >= self._max_queue_frames:
                self._queue_not_full.wait(timeout=1.0)
                if self._writer_error_event.is_set():
                    raise self._writer_error or RuntimeError("FFmpeg 写入线程出错")
        self._frame_queue.put(data)
        self._queue_frame_size += 1
        return True

    def cleanup(self) -> None:
        """清理资源。

        按顺序完成：
        1. 停止异步写入线程（发送哨兵信号并等待消费完毕）
        2. 关闭 stdin 管道，通知 FFmpeg 输入结束
        3. 等待 stderr 线程结束（避免日志丢失）
        4. 等待 FFmpeg 进程退出
        5. 关闭 stderr 管道，释放资源
        """
        # 第一步：停止异步写入线程
        if self._frame_queue is not None and self._writer_thread is not None:
            self._frame_queue.put(self._SENTINEL)
            logger.info("等待写入线程完成...")
            self._writer_thread.join(timeout=300.0)
            if self._writer_thread.is_alive():
                logger.warning("写入线程超时，强制终止")
            else:
                logger.info("写入线程已完成")

        proc = self.process
        if proc is None:
            return

        # 第二步：关闭 stdin，通知 FFmpeg 输入结束
        if proc.stdin:
            try:
                proc.stdin.close()
            except (OSError, BrokenPipeError):
                pass

        # 第三步：等待 stderr 线程结束，确保日志不丢失
        if self.stderr_thread and self.stderr_thread.is_alive():
            self.stderr_thread.join(timeout=self.system_params.stderr_thread_timeout)

        # 第四步：等待 FFmpeg 进程退出
        logger.info("等待 FFmpeg 完成编码...")
        try:
            return_code = proc.wait(timeout=300.0)
            if return_code == 0:
                logger.success(f"压制完成: {self.video_out}")
            else:
                logger.error(f"压制失败 (code={return_code})")
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg 超时，强制终止")
            proc.kill()
            proc.wait()
        finally:
            # 第五步：关闭 stderr 管道，释放资源
            if proc.stderr:
                try:
                    proc.stderr.close()
                except (OSError, BrokenPipeError):
                    pass
            self.process = None