# 提交信息规范

本项目采用 [Conventional Commits](https://www.conventionalcommits.org/) 约定。

## 格式

```
<type>[(<scope>)]: <subject>

[body]
```

## Type（类型）

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响逻辑） |
| `refactor` | 重构（非修复非功能） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统或外部依赖 |
| `ci` | CI 配置 |
| `chore` | 其他杂务 |
| `release` | 版本发布 |

## Scope（范围）

使用模块/文件简名，如 `config` `encode` `render` `core` `parser` `logging` `cli` 等。

## 规则

1. **Subject 不超过 72 字符**，使用英文现在时，首字母小写，句末不加句号。
2. **Body 可选**，仅在需要补充说明时添加，每行不超过 72 字符，解释 **做了什么** 和 **为什么**。
3. **禁止** 在提交信息中贴测试输出、覆盖率数值、命令执行日志等工程噪声。
4. 破坏性变更在 type/scope 后加 `!`，或在 body 末尾加 `BREAKING CHANGE:` 段落。

## 示例

```
feat(config): add configurable danmaku colors and bounded delay params

Color fields (normal, gift, incoming, username) are now read from
user config, replacing hardcoded values.  Added max_spawn_latency
for adaptive spawn interval adjustment under backlog.
```

```
fix(encode): remove hardcoded H.264 decoder, fallback to CPU on unsupported codecs

GPU/QSV pipelines assumed input is always H.264, breaking HEVC/VP9/MPEG4.
Let ffmpeg auto-select decoder via -hwaccel; probe codec support at runtime
and fall back to CPU when hardware decode is unavailable.
```

```
refactor(config)!: switch defaults to project recommendations, user-private config

BREAKING CHANGE: built-in defaults changed from DanmakuFactory defaults to
DanmakuPro recommended values.  User config file is now private per install.
```