# ADR-0007：移除 VFR 判定与局部帧率采样

- **状态**：已采纳并实施
- **日期**：2026-09-17
- **影响模块**：`encode/ffmpeg.py`（`_detect_vfr`、`_sample_local_frame_rates`）、
  `core/burner.py`

## 背景

`get_video_info` 曾在主路径上做一次 VFR 判定：用 `ffprobe -read_intervals` 在视频前、
中、后各采样 5 秒，比较三段局部帧率的相对极差，超过 2% 即判为变帧率。判定结果只有
一处消费者 —— `DanmakuBurner` 打印一条提示观感的 WARNING。

它不改变任何一帧：不参与编码命令构建，不参与渲染帧率计算，也不参与时间轴长度。
弹幕时间轴与画面的对齐由 `frames / duration` 保证（见 ADR-0001），与帧率是否恒定无关。

## 决策

删除整条 VFR 判定链：

1. 常量 `_VFR_SAMPLE_TOLERANCE`、`_VFR_SAMPLE_SECONDS`；
2. `FFmpegManager._detect_vfr()` 与 `FFmpegManager._sample_local_frame_rates()`；
3. `get_video_info()` 返回字典中的 `vfr` 字段；
4. `burner.py` 中消费该字段的 WARNING 分支。

帧率口径部分（`_resolve_render_fps` + `_probe_packet_count`）保持不变。

## 依据

**判定不影响产物，收益仅限于一句提示**：`src/` 内 `vfr` 字段的唯一读点是
`burner.py` 的 `logger.warning`。移除前后逐帧产物完全相同。

**成本与收益倒挂**（23.6s / 1088x1920 / 474 帧 / GPU 实测）：端到端 7.8s 中，三次
采样的 ffprobe 合计 2.88s，占 36.8%；该素材判定为 CFR，这 2.88s 换来的输出为零。
同期「数包取真实帧数」这条必需探测只用 0.99s。

**不能靠缩短采样窗口降本**：把三段合并为单次区间窗口时，9/9 素材判定一致，总耗时
26.22s → 22.14s（省 16%）；但窗口再缩到 1s 后，9 份素材里有 2 份把 CFR 误判成 VFR ——
采样窗口必须覆盖足够的帧才能区分「真实波动」与「局部瞬时抖动」，这是判据本身的下界，
无法通过调参绕开。

**判定从来不是处理 VFR 的手段**：对 VFR 素材的真正保障是「弹幕层时长 = 视频时长」。
渲染帧率取 `frames / duration`，弹幕层总帧数即视频真实帧数，二者之比恒等于时长；
合成阶段 overlay 用 framesync 按时间戳配对两个流（受控实验：画面不等间隔、弹幕等间隔
时配对为 `0,1,3,3,5,5,5,8,8,8`，是跳帧而非按序配对），帧率波动本身不造成漂移。强制转
CFR 需要丢帧或复制帧并改动 GPU 滤镜链，收益不成立，故未采纳。

## 后果

- 每次压制省去 3 次 ffprobe（实测该素材上约占端到端 36.8%）。
- 失去 VFR 素材的自动观感提示。README 相应删去「运行时会给出提示」，并给出自助判据
  （`ffprobe -show_entries frame=pts_time` 看帧间隔是否均匀）。
- ADR-0001 中与 VFR 判据相关的部分（采样方式、2% 阈值、丢弃 pts 非单调段）随之废止；
  该 ADR 的帧率口径与包数选型部分继续有效。
