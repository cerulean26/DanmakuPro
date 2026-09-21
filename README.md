# DanmakuPro

抖音直播弹幕压制工具 — 将直播录像与弹幕 XML 合成，以半透明圆角气泡形式将弹幕永久烧录到视频中。

## 特性

- **GPU 硬件加速** — CUDA 解码 (NVDEC) + NVENC 编码，叠加合成在 CPU 侧完成；支持 QSV 与 CPU 管线
- **双区布局** — 礼物区（上方）+ 文本弹幕区（下方），互不干扰
- **空间驱动布局** — 弹幕从底部向上堆叠，含碰撞检测，互不遮挡
- **阻尼动画** — 弹幕/礼物位移带平滑插值过渡，视觉自然流畅
- **礼物停留时间** — 可配置礼物在屏幕上的最大停留时长，超时自动消失
- **Emoji 内联渲染** — 支持 `[笑哭]` `[666]` 等弹幕表情，按需懒加载
- **礼物过滤** — 可按礼物价格阈值过滤，仅保留有价值的礼物弹幕
- **预渲染缓存** — 每条弹幕预渲染为 QImage，后续帧仅需一次 drawImage
- **字体回退** — 多字体族链式匹配，未覆盖字符自动回退到扩展字体

## 环境要求

| 项目 | 要求 |
|---|---|
| Python | ≥ 3.13 |
| FFmpeg | `ffmpeg` 与 `ffprobe` 都需在 PATH 中；GPU 加速需编译 NVDEC / NVENC 支持 |
| NVIDIA 显卡 | 可选，驱动支持 CUDA 时可启用 GPU 编码 |
| 操作系统 | Windows / Linux / macOS，需真实桌面环境（依赖系统字体） |

Python 运行时依赖：`lxml` `PySide6` `loguru` `tqdm` `pyyaml`（声明于 `pyproject.toml`）。

> **不支持无头服务器**：Qt 在 `QT_QPA_PLATFORM=offscreen` 下拿不到字体引擎，字形会退化成豆腐块，`--check` 的字体覆盖结论也会偏乐观。本项目定位是桌面工具。

## 安装

### 1. 安装 FFmpeg

本项目不打包 ffmpeg，请单独安装并将 `ffmpeg` 和 `ffprobe` 加入系统 PATH：

| 方式 | 命令 |
|------|------|
| **winget**（Windows 推荐） | `winget install ffmpeg` |
| **scoop** | `scoop install ffmpeg` |
| **brew**（macOS） | `brew install ffmpeg` |
| **apt**（Debian/Ubuntu） | `sudo apt install ffmpeg` |

安装后验证：`ffmpeg -version` 与 `ffprobe -version` 都应打印版本号。

### 2. 安装 DanmakuPro

**方式一：源码检出（推荐）**

```bash
git clone https://github.com/cerulean26/DanmakuPro.git
cd DanmakuPro

uv sync                # 运行时依赖
uv sync --group dev    # 追加 pytest / pytest-cov / ruff / pyright（要改代码或跑测试时）
```

不用 uv 时，pip 的等价做法：

```bash
pip install .                                # 装本包，运行时依赖一并装上
pip install pytest pytest-cov ruff pyright   # 需要跑测试与静态检查时再补
```

> 构建后端是 hatchling + hatch-vcs，版本号由 git 元数据推导，因此请在**完整的 git 检出**里构建，不要拿缺失 `.git` 的目录副本。

**方式二：安装已构建的发行包**

CI 在推送 `v*` 标签时会把 wheel 与 sdist 发布到 [GitHub Releases](https://github.com/cerulean26/DanmakuPro/releases)：

```bash
pip install danmakupro-<版本>-py3-none-any.whl
```

> 本项目**未发布到 PyPI**，`pip install danmakupro` 会报找不到包 —— 请改用上面两条路径。

### 3. 验证安装

```bash
danmakupro --help
```

`danmakupro` 由 `pyproject.toml` 注册为控制台脚本（`danmakupro.cli:main`）。若它不在 PATH 上（例如忘了激活虚拟环境），等价替代是：

```bash
python -m danmakupro.cli --help
```

## 素材要求

### 支持的格式

| 用途 | 允许的扩展名 |
|---|---|
| 输入视频 | `.mp4` `.flv` `.mkv` `.avi` `.mov` `.ts` `.webm` |
| 输出视频 | `.mp4` `.flv` `.mkv` `.avi` `.mov` |

> 输出**不支持** `.ts` / `.webm`：`-o out.ts` 会以 `[input] 不支持的输出格式: .ts` 失败退出。默认输出扩展名是 `.mp4`。

### 变帧率（VFR）素材

**变帧率（VFR）素材可直接使用**：弹幕层与画面按时间轴对齐，渲染帧率取真实平均帧率（优先读容器 `nb_frames`，缺失时用 `ffprobe -count_packets` 实测），因此弹幕时间轴长度恒等于视频时长，既不漂移也不丢尾部弹幕。仅当全片帧率剧烈波动时弹幕运动可能略有顿挫；若在意观感，可先用 `ffprobe -show_entries frame=pts_time` 看帧间隔是否均匀，确实不均再 `ffmpeg -i in.flv -vsync cfr out.mp4` 转成 CFR 压制（代价是丢帧或复制帧）。

### 资源目录

- Emoji 图片放 `assets/emoji/`，礼物图片放 `assets/gift/`（根目录名可由 `system.assets_dir` 调整）。
- 资源缺失**不会中断压制**，对应元素显示为占位符；`--check` 可提前拿到完整缺失清单。

## 快速开始

### 1. 准备素材

直播录像与抖音弹幕 XML 放一起，Emoji 与礼物图片放入 `assets/`：

```
source/视频.flv
source/视频.xml
assets/emoji/*.png
assets/gift/*.png
```

### 2. 运行

```bash
danmakupro source/视频.flv source/视频.xml
```

默认输出到输入视频旁的 `source/视频-弹幕版.mp4`。

### 3. 第一次跑新素材，建议先体检

```bash
danmakupro source/视频.flv source/视频.xml --check
```

`--check` 是纯检查模式：输出视频元数据、弹幕事件统计、发射能力评估（需求速率 vs 基础能力、是否依赖自适应加速）、字体覆盖率（含缺失字符及其 Unicode 码点）、Emoji / 礼物图片缺失清单与最终选中的编码管线。它不产出任何文件，也不会被上次失败留下的残缺输出挡住。

## 使用示例

### 示例 1：默认压制（CPU 编码）

```bash
danmakupro source/视频.flv source/视频.xml
```

不指定 `--encode` 时走 `h264`（libx264 + CPU）。一段 1088x1920、24 秒、474 帧的素材实测 7.9 秒压完，日志尾部形如：

```
[4] 准备就绪 → 启动 FFmpeg
完成: 474 帧, 7.9s, 弹幕 37/37 + 礼物 0/0
SUCCESS - 压制完成: source/视频-弹幕版.mp4
```

### 示例 2：指定编码模式与输出路径

```bash
danmakupro source/视频.flv source/视频.xml --encode h264_nvenc -o output/成片.mp4
```

`--encode` 的合法取值共 9 个：`h264` `h264_nvenc` `h264_qsv` `h265` `h265_nvenc` `h265_qsv` `av1` `av1_nvenc` `av1_qsv`。写错会被直接拒绝（退出码 `2`）：

```
danmakupro: error: argument --encode: invalid choice: 'gpu'
            (choose from h264, h264_nvenc, h264_qsv, h265, h265_nvenc, h265_qsv, av1, av1_nvenc, av1_qsv)
```

硬件管线**不可用时直接报错退出，不会静默降级**为 CPU；但选中 GPU/QSV 而输入格式无法硬解时，会自动改用 CPU 并打 WARNING。完整对照表见 [docs/configuration.md](docs/configuration.md#--encode-与硬解回退)。

### 示例 3：生成并使用配置模板

```bash
danmakupro --init-config                        # 写出 ./danmakupro.yaml（已存在时不覆盖）
danmakupro --init-config -c configs/my.yaml     # 指定生成路径
danmakupro source/视频.flv source/视频.xml      # 当前目录的 danmakupro.yaml 会被自动加载
```

也可以手动复制 `src/danmakupro/danmakupro.example.yaml` 成 `./danmakupro.yaml` 或 `~/danmakupro.yaml`。查找顺序为 `-c` → 当前目录 → 用户目录，**只取第一个存在的，不合并**，每次运行都会在日志里打印实际加载的配置文件绝对路径。

### 示例 4：批量压制一批录像

```bash
mkdir -p output
for v in source/*.flv; do
  name="${v##*/}"; name="${name%.*}"
  danmakupro "$v" "${v%.flv}.xml" -o "output/${name}-弹幕版.mp4" -f
done
```

要点（整段已在 Git Bash 下实跑验证）：

- **输出目录必须先存在**：`-o` 指向不存在的目录会以「输出目录不存在」失败，所以先 `mkdir -p output`。
- **变量一律加引号**：抖音录像文件名普遍带空格，不加引号会被拆成多个参数。
- `${v%.flv}.xml` 依赖「视频与 XML 同名」这一约定。
- 取文件名与去扩展名要写成**两句**：先 `name="${v##*/}"`，再 `name="${name%.*}"`。别图省事写 `${v##*/%.*}` —— `%` 会被当作 `##` 模式的一部分，实测得到的是 `output/source/xxx.flv.mp4` 这种错路径。
- `-f` 让重复运行不会卡在覆盖询问上。

### 示例 5：输出文件已存在时

默认输出是输入视频旁边的 `<视频名>-弹幕版.mp4`，极易与上次的产物重名。此时程序既不报错也不默默覆盖，而是在终端问一次：

```
输出文件已存在: source/5-弹幕版.mp4（0 字节，最后修改 2026-09-16 00:44）
是否覆盖该文件？[y/N]
```

| 应答 | 结果 |
|---|---|
| `y` / `yes` | 覆盖原文件并继续压制 |
| `n` / `no` / 直接回车 / `Ctrl+C` | 保留原文件，以退出码 `1` 结束 |
| 命令行加 `-f` | 不询问，直接覆盖 |

提示里带上体积与最后修改时间，便于判断是否需要保留该文件。

**非交互环境不询问**：管道、重定向、CI 或由其他程序调用时 stdin 不是终端，`input()` 要么立刻拿到 EOF、要么永久阻塞等待一个不会到来的输入，两者都不是期望行为。因此一律按「不覆盖」处理，并提示加 `-f`：

```
WARNING - 输出文件已存在: output\成片.mp4（9.9 MB，最后修改 2026-09-21 16:52:31）
ERROR - [input] 输出文件已存在，已取消覆盖: output/成片.mp4
如需覆盖请加 -f，或改用 -o 指定其他输出路径。
```

### 示例 6：退出码与中断

| 退出码 | 含义 |
|---|---|
| `0` | 压制成功 |
| `1` | 失败（输入无效、编码错误、拒绝覆盖等） |
| `2` | 参数不合法（缺 `video` / `xml`、`--encode` 取值非法） |
| `130` | 用户中断（Ctrl+C） |

按 `Ctrl+C` 中断时，程序先等 FFmpeg 收尾、删除不完整的输出文件，再以 `130` 退出 —— 这样脚本与上层调用方不会把「被取消」误判成「压制成功」，也不会残留残缺的 mp4 挡住下次运行。

## 布局说明

弹幕渲染区域分为上下两个独立区域：

```
┌──────────────────────────────┐
│         礼物区（上方）         │  ← 可配置行数（默认 2 行）
│   礼物弹幕从下往上堆叠        │     独立阻尼、淡出、停留时间
├──────────────────────────────┤
│        文本弹幕区（下方）      │  ← 可配置行数（默认 8 行）
│   文本弹幕从下往上堆叠        │     含碰撞检测与推挤
└──────────────────────────────┘
```

## 处理流程

```
XML 解析 → 资源加载 → 视频信息获取 → 弹幕布局计算 → 逐帧渲染 → FFmpeg 合成
```

1. 流式解析抖音弹幕 XML，提取 `<d>` 和 `<gift>` 标签
2. 加载 Emoji 和礼物图片资源，按需加载字体
3. 通过 ffprobe 获取视频宽高、帧率、总帧数（与步骤 1-2 并发执行）
4. 计算布局参数（弹幕行数 / 宽度比例）
5. 构建 FFmpeg 编码管线（自动检测 NVENC / QSV / CPU；探测结果进程内缓存，仅首次耗时）
6. 逐帧惰性创建并渲染弹幕气泡图层，通过管道送入 FFmpeg，输出压制视频

## 配置

**不改配置也能直接用** —— 不提供配置文件时程序使用内置默认值，这些值是针对直播素材长期调优的推荐值。需要调参时用 `danmakupro --init-config` 生成带注释的模板。

完整参数表（40 项 / 5 个分组）、配置文件查找顺序（`-c` → 当前目录 → 用户目录的优先级），以及配置文件的归属约定，见 **[docs/configuration.md](docs/configuration.md)**。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| `不支持的输出格式: .xxx` | 输出扩展名仅限 `.mp4` `.flv` `.mkv` `.avi` `.mov`；换成其中之一即可 |
| `输出目录不存在: xxx` | `-o` 指向的目录必须先存在，程序不会代为创建 |
| `视频文件不存在` / `弹幕 XML 文件不存在` | 路径写错，或用了相对路径但当前工作目录不对 |
| `不支持的视频格式: .xxx` | 输入扩展名须在 `.mp4` `.flv` `.mkv` `.avi` `.mov` `.ts` `.webm` 之内 |
| 退出码 `1` 且提示 `输出文件已存在，已取消覆盖` | 非交互环境按不覆盖处理，加 `-f` 或换 `-o` |
| 日志在哪 | 源码检出写 `logs/danmakupro.log`；pip 安装后写用户级目录（Windows `%LOCALAPPDATA%\DanmakuPro\logs`）。`DANMAKUPRO_LOG_DIR` 可覆盖 |
| 弹出的字符是豆腐块 | 当前环境取不到字体引擎（常见于无头/远程会话），请在真实桌面环境运行 |

## 贡献指南

### 准备开发环境

```bash
git clone https://github.com/cerulean26/DanmakuPro.git
cd DanmakuPro
uv sync --group dev
```

### 提交前必须跑通四条门禁（与 CI 逐条对应）

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pyright
uv run pytest tests/ -m "not gpu and not slow"
```

四条都要干净才提交。改动前的基线供参照：`ruff` 全通过、`pyright` 0 error、`pytest` 422 passed、语句覆盖率 96%（阈值 85%）。

- `pyright` **故意不传路径**：检查范围由 `pyproject.toml` 的 `[tool.pyright] include` 决定，命令行一旦写了路径反而会覆盖该配置。
- `ruff check`（找可疑写法）与 `ruff format`（只管排版）是两件事，必须成对出现，否则下一个提交就会重新漂移。
- 覆盖率阈值由 `pyproject.toml` 的 `[tool.coverage.report] fail_under` 提供，不要在命令行再传 `--cov-fail-under`。

### 改动静音链路后补跑真机用例

改动 `encode/`、`core/`、`render/` 之后，请在本机额外跑一遍真机端到端用例：

```bash
pytest tests/test_e2e_burn.py -m slow
```

它会真实调用 ffmpeg / ffprobe，把一段用 lavfi 合成的视频压制一遍，再反查产物的分辨率、帧数、时长与**像素内容**（弹幕是否真的画上去、是否在尾部冻住）—— 覆盖单测覆盖不到的一类问题：滤镜图写错、帧率口径算错、弹幕层根本没叠加。这批用例标记为 `slow`，CI 不安装 ffmpeg，故默认排除；未装 ffmpeg 的环境会自动跳过，不会造成假失败。

### 提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/)：`<type>[(<scope>)]: <subject>`。

- **type**：`feat` `fix` `docs` `style` `refactor` `perf` `test` `build` `ci` `chore` `release`
- **scope**：模块简名，如 `config` `encode` `render` `core` `parser` `logging` `cli`
- **subject**：不超过 72 字符，英文现在时，首字母小写，句末不加句号
- 提交信息里**不要**贴测试输出、覆盖率数值、命令执行日志

完整说明与示例见 [.github/COMMIT_CONVENTION.md](.github/COMMIT_CONVENTION.md)。

### 改动须知

- 修改 `src/danmakupro/config/models.py` 的字段默认值，必须同步 `src/danmakupro/danmakupro.example.yaml` —— 逐字段一致性由 `tests/test_config_example.py` 断言，只改一边会立刻变红。
- 涉及架构取舍的改动，请在 `docs/decisions/` 下补一篇 ADR（现有 8 篇，编号递增）。
- `assets/`、`source/`、`logs/` 与 `/danmakupro.yaml` 都不入版本控制 —— 别把本地素材、日志或私有配置塞进提交。
- 更多细节（项目结构树、无头环境的限制、e2e 用例的定位）见 **[docs/development.md](docs/development.md)**。

### 提交流程

1. Fork 仓库并新建分支（`feature/xxx`、`fix/xxx`）
2. 本地跑通四条门禁，需要时补跑 `slow` 用例
3. 向 `main` 发 Pull Request，说明改了什么、为什么这么改
4. 等 CI 绿：Linux 侧跑 ruff + pyright，Windows 侧跑 pytest（Windows job 不安装 ffmpeg，故排除 `slow` 用例）

## 许可证

GPLv3 — 详见 [LICENSE](LICENSE)