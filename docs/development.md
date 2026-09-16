# 开发

[← 返回 README](../README.md)

## 项目结构

```
DanmakuPro/
├── src/danmakupro/           # 核心包
│   ├── cli.py                # CLI 入口
│   ├── errors.py             # 错误类型与分类
│   ├── logger_config.py      # 日志配置
│   ├── danmakupro.example.yaml  # 配置模板（`--init-config` 的来源，随包分发）
│   ├── config/               # 配置模块
│   │   ├── models.py         # 配置数据模型
│   │   └── loader.py         # YAML 配置加载
│   ├── core/                 # 核心引擎
│   │   ├── burner.py         # 压制编排（准备阶段与生命周期）
│   │   └── pipeline.py       # 逐帧渲染主循环
│   ├── input/                # 输入模块
│   │   ├── event.py          # 弹幕事件数据模型
│   │   └── parser.py         # 抖音 XML 流式解析
│   ├── layout/               # 布局模块
│   │   ├── engine.py         # 布局计算、发射节流与碰撞检测
│   │   ├── active.py         # 活跃弹幕运行时状态
│   │   └── params.py         # 布局参数数据类
│   ├── render/               # 渲染模块
│   │   ├── renderer.py       # 画布管理与帧渲染
│   │   ├── active_view.py    # 弹幕预渲染与绘制
│   │   ├── layout_builder.py # 气泡布局与折行
│   │   ├── segments.py       # 渲染段落与文本行
│   │   └── assets.py         # 资源加载（字体、图片）
│   ├── encode/               # 编码模块
│   │   └── ffmpeg.py         # FFmpeg 进程管理与编码器探测
│   └── utils/                # 工具模块
│       ├── helpers.py        # 通用工具函数
│       └── validation.py     # 输入输出校验
├── tests/                    # 测试（19 个模块；test_e2e_burn.py 为真机用例，标记 slow）
├── docs/                     # 文档
│   ├── configuration.md      # 完整参数表与配置查找规则
│   └── development.md        # 本文件
├── assets/                   # Emoji / 礼物 PNG / 特效资源（本地，未纳入版本控制）
│   ├── emoji/
│   ├── gift/
│   └── effect/
├── source/                   # 示例素材：视频 + 弹幕 XML（本地，未纳入版本控制）
├── danmakupro.yaml           # 你的本地配置（可选，未纳入版本控制）
├── pyproject.toml
└── README.md
```

## 质量门禁

与 CI 完全一致的四条命令（`ci.yml` 的扫描范围就是 `src/` 与 `tests/`）：

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pyright
uv run pytest tests/ -m "not gpu and not slow"
```

`pyright` 故意不传路径：检查范围由 `pyproject.toml` 的 `[tool.pyright] include` 决定（`src` + `tests`）；命令行一旦写了路径，反而会覆盖该配置。

`ruff check`（静态分析，找可疑写法）与 `ruff format`（只管排版）管的是两件事。只跑 `format` 而不在 CI 卡住，下一个提交就会重新漂移，所以这两条必须成对出现。

覆盖率阈值由 `pyproject.toml` 的 `[tool.coverage.report] fail_under` 提供，不要在命令行再传 `--cov-fail-under`。测试套件不依赖 `assets/`、`source/` 等本地素材（e2e 用例的视频由 lavfi 合成）。

> 改动 `config/models.py` 的字段默认值时，必须同步修改 `src/danmakupro/danmakupro.example.yaml` —— 两者的逐字段一致性由 `tests/test_config_example.py` 断言，只改一边会直接变红。

## 真机端到端用例（`slow`）

`tests/test_e2e_burn.py` 会**真实调用 ffmpeg / ffprobe**，把一段用 lavfi 合成的 2 秒视频压制一遍，再反查产物的分辨率、帧数、时长与**像素内容**（弹幕有没有真的画上去、有没有在尾部冻住）。它覆盖单测覆盖不到的一类问题：滤镜图写错、帧率口径算错、弹幕层根本没叠加。

这批用例被标记为 `slow`，而 CI 不安装 ffmpeg，所以在 CI 中被排除。**改动静音链路（`encode/`、`core/`、`render/`）后请在本机跑一遍：**

```bash
pytest tests/test_e2e_burn.py -m slow
```

未安装 ffmpeg / ffprobe 的环境会自动跳过，不会造成假失败。

> **无头环境的限制（2026-09-15 实测）**：Qt 在 `QT_QPA_PLATFORM=offscreen` 下拿不到字体引擎 —— `QFontDatabase().families()` 返回空列表，`QRawFont` 查询字形会直接段错误。此时字形渲染退化为「豆腐块」（每个字变成空心方框），且 `--check` 的字体覆盖判定会给出**偏乐观**的结论。这批用例因此只能验证「弹幕层有没有叠上去、有没有在尾部冻住」，**验证不了「文字本身有没有正确渲染」**—— 后者请在真实桌面环境下实跑一次压制确认。本项目定位是桌面工具（依赖系统字体），无头服务器场景不在支持范围内。
