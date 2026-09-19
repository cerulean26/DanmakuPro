# ADR-0005：`get_frame_data` 返回零拷贝视图而非副本

- **状态**：已采纳并实施
- **日期**：2026-09-16
- **影响模块**：`render/renderer.py`（`RenderEngine.get_frame_data`）

## 背景

`QImage.bits()` 返回的是画布内存的**视图**而非副本。下一次 `render_frame()` 开头的
`canvas.fill()` 会就地改写这块内存，此前取到的 `memoryview` 内容随之改变。

## 决策

返回视图，不返回副本。

## 依据

当前唯一调用方 `RenderPipeline._encode_frame` 是**同步**写 stdin，写完才继续绘制下一帧，
因此视图在写入期间始终有效 —— 零拷贝是安全的。

若将来改为异步 / 多线程写入，**必须**改成返回独立副本：

```python
return bytes(memoryview(self.canvas.bits()))
```

否则写入线程会读到被下一帧覆盖的半新半旧画面。2026-09-16 实测的故障形态：228 帧中
224 帧损坏，并伴随段错误退出。

## 后果

- 省下每帧一次整屏像素拷贝。
- 正确性依赖于「写入同步完成」这个隐含前提，已写进方法文档串的警告里。
