# ADR-0006：中断不以 returncode 判定，单独标记 `interrupted`

- **状态**：已采纳并实施
- **日期**：2026-09-16
- **影响模块**：`encode/ffmpeg.py`（`cleanup`、`interrupted` 标记）

## 背景

用户中断（Ctrl+C）后，FFmpeg 子进程有两种互不相同的死法，返回码也不一样：

| 中断形态 | FFmpeg 收尾方式 | returncode |
|---|---|---|
| 真实控制台按键 Ctrl+C | 信号连带送到子进程，被信号杀掉 | **255**（Windows 实测） |
| 仅在 Python 侧中断 | 收不到信号，按 stdin EOF 正常收尾 | **0** |

第二种尤其危险：只看 `returncode` 会把它误判成「压制完成」。

## 决策

在实例上单独维护 `interrupted` 标记；`cleanup()` 里优先判它，命中则一律按「中断」
记录（`logger.warning`），**不用 ERROR** —— 用户主动中断不是错误，且两种形态下产物
同样残缺，处理方式应当一致。

## 依据

「中断」与「成功 / 失败」是两个正交维度：前者描述**谁发起的**，后者描述**结果是否完整**。
用户中断既要清理残缺产物（与失败相同），又不该在日志里表现为程序故障（与失败不同）。

判定 `interrupted` 必须在 Python 侧独立完成，不能依赖子进程的返回码 —— 因为上表第二行
的返回码与成功路径完全一致。

## 后果

- 中断路径不会误报「压制完成」，也不会被当成程序错误。
- 前提是中断信号确实送达了 Python 主进程；若将来改变信号处理方式，需重新核对
  `interrupted` 的置位时机。

## 复现与验证的注意点

本项目无法在 Windows 上程序化模拟「真实 Ctrl+C」（`CREATE_NEW_PROCESS_GROUP` +
`os.kill(pid, CTRL_C_EVENT)` 会被该标志屏蔽；不带标志又会波及自身进程）。
**只在 Python 侧 `raise KeyboardInterrupt` 的验证是无效的** —— 它只覆盖上表第二行，
ffmpeg 收不到信号、按 EOF 正常收尾（code=0），走的完全是另一条分支。详见
`.workbuddy/reviews/2026-09-16-project-code-audit.md` 与项目记忆中的验证纪律。
