# ADR-0003：stderr 一律写成 UTF-8，CPU 作为唯一真正的降级目标

- **状态**：已采纳并实施（`_ensure_utf8_stderr` 保留原逻辑，仅订正文档串的因果）
- **日期**：2026-09-16
- **影响模块**：`logger_config.py`（`_ensure_utf8_stderr`、`resolve_log_dir`）

## 背景

先前 `_ensure_utf8_stderr` 的文档串声称「Windows 中文环境下 stderr 为 cp936，中文会
直接输出成乱码」。2026-09-16 的三组实验证明这个因果是**反的**。

## 决策

维持「把 stderr 的写出编码钉到 UTF-8」不变，因为函数的实际作用域比注释声称的窄得多。

## 依据（实测）

**实验一 —— conhost 的解码规则**（`CreateConsoleScreenBuffer` 开后台屏幕缓冲，对同一句
中文做三种写入 × 两种代码页，用 `ReadConsoleOutputW` 读回 conhost 的真实解码结果）：

| 写入方式 | CP 936 | CP 65001 |
|---|---|---|
| `WriteFile`(GBK 字节) | 正确 | 乱码 |
| `WriteFile`(UTF-8 字节) | 乱码 | 正确 |
| `WriteConsoleW`(宽字符) | 正确 | 正确 |

→ 写入字节与控制台代码页一致才正确；**宽字符路径与代码页无关**。cp936 字节在 936
终端下是正确显示的 —— 旧注释把因果写反了。

**实验二 —— 真实控制台上本函数是空操作**：把真实 `CONOUT$` 句柄塞给子进程当 stderr
（诊断确认 `GetFileType=2 CHAR`、`GetConsoleMode` 成功），Python 3.13 的 stderr 默认
已是 UTF-8 且走宽字符路径，`reconfigure` 前后渲染都正确。

**实验三（决定性）—— 只有重定向场景才真正改变字节**（stderr 重定向到文件后读取）：

| | 写出的字节 | 按 GBK 解读 |
|---|---|---|
| 不调用 reconfigure | `B1 E0 C2 EB C4 A3 CA BD` | 编码模式 ✅ |
| 调用 reconfigure | `E7 BC 96 E7 A0 81 E6 A8 A1 E5 BC 8F` | **缂栫爜妯″紡** ❌ |

历史上记录的乱码串 `缂栫爜妯″紡`，正是 **UTF-8 字节被按 GBK 解读**的结果 —— 即本函数
重配之后的写出内容，而不是被它修掉的内容。

## 后果

- 本函数在真实控制台上无事可做，也不害人。
- 它的作用域只有「stderr 被重定向」（CI 日志、管道交给别的程序、集成终端窗口捕获）。
  在那个场景里它是一次押注：读取端是 UTF-8（Windows Terminal / VS Code / 现代 CI 容器）
  就正确；读取端仍按 GBK 解读则会从「正确」变成乱码。
- 若将来要收紧，正确做法是「已是 UTF-8 则跳过 + 尊重 `PYTHONIOENCODING`」，
  **不要**加 GBK 特判 —— GBK 没有 emoji 等码位，`--check` 报告里的图标会必然丢字符
  （那是字符集问题，不是代码页问题）。

## 附：日志目录三级判定（`resolve_log_dir`）

wheel 安装后原实现的 `Path(__file__).parent.parent.parent / "logs"` 会落到 Python 的
`Lib/`，系统级安装时 `PermissionError` 直接启动即崩。现按三级判定：环境变量
`DANMAKUPRO_LOG_DIR` > 源码检出（存在 `src/danmakupro`）用 `根/logs` > 已安装用用户级
目录（win `%LOCALAPPDATA%`，其它 `$XDG_STATE_HOME` / 回落 `~/.local/state`）。

没有为此引入 `platformdirs` 依赖 —— 判定只需 6 行分支。已用 `uv build` 出 wheel 装到
临时 venv 真机验证三种场景 `exit=0`，日志目录均不在解释器目录内。

目录在 `configure_logger()` **调用时**才求值，模块级不缓存：实现里原本有个
`_LOG_DIR = resolve_log_dir()` 的模块级常量，若环境变量在 import 之后才设置就不生效，
且目录出现「常量 / 函数」两个真相（测试只能改私有全局来隔离）。日志文件名定为
`danmakupro.log`：文件 sink 装的是全应用日志（`encode.ffmpeg` 只占约四分之一，
其余为 `core.burner` / `utils.validation` / `cli` / `config.loader`），旧名
`ffmpeg.log` 会让使用者误以为只记 ffmpeg；且 ffmpeg 的常规输出经分流后走 debug、
不落 INFO 文件 sink，旧名更是名实两违。
