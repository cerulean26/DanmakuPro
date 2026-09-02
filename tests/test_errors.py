from danmakupro.errors import (
    ErrorCategory, ErrorContext, DanmakuProError,
    InputError, ConfigError, RenderError, EncodeError, ResourceError,
    ErrorHandler, handle_error,
)


# =============================================================================
# ErrorContext
# =============================================================================

class TestErrorContext:

    def test_default_values(self):
        ctx = ErrorContext()
        assert ctx.frame_idx is None
        assert ctx.task_id is None
        assert ctx.component is None
        assert ctx.operation is None
        assert ctx.details is None

    def test_with_values(self):
        ctx = ErrorContext(frame_idx=42, component="test", details={"key": "val"})
        assert ctx.frame_idx == 42
        assert ctx.component == "test"
        assert ctx.details == {"key": "val"}


# =============================================================================
# 自定义异常
# =============================================================================

class TestCustomExceptions:

    def test_danmakupro_error(self):
        e = DanmakuProError("test msg")
        assert str(e) == "test msg"
        assert e.category == ErrorCategory.UNKNOWN
        assert isinstance(e.context, ErrorContext)

    def test_danmakupro_error_with_context(self):
        ctx = ErrorContext(frame_idx=5)
        e = DanmakuProError("msg", category=ErrorCategory.RENDER, context=ctx)
        assert e.category == ErrorCategory.RENDER
        assert e.context.frame_idx == 5

    def test_input_error(self):
        e = InputError("bad input")
        assert e.category == ErrorCategory.INPUT
        assert isinstance(e, DanmakuProError)

    def test_config_error(self):
        e = ConfigError("bad config")
        assert e.category == ErrorCategory.CONFIG
        assert isinstance(e, DanmakuProError)

    def test_render_error(self):
        e = RenderError("render failed")
        assert e.category == ErrorCategory.RENDER

    def test_encode_error(self):
        e = EncodeError("encode failed")
        assert e.category == ErrorCategory.ENCODE

    def test_resource_error(self):
        e = ResourceError("missing resource")
        assert e.category == ErrorCategory.RESOURCE

    def test_inheritance_chain(self):
        e = InputError("test")
        assert isinstance(e, DanmakuProError)
        assert isinstance(e, Exception)


# =============================================================================
# ErrorHandler
# =============================================================================

class TestErrorHandler:

    def test_handle_danmakupro_error(self):
        e = InputError("input error", context=ErrorContext(frame_idx=10))
        ErrorHandler.handle(e)

    def test_handle_standard_exception(self):
        ErrorHandler.handle(ValueError("bad value"))

    def test_handle_with_context(self):
        ctx = ErrorContext(component="parser", operation="validate")
        ErrorHandler.handle(RuntimeError("oops"), context=ctx)

    def test_handle_with_details(self):
        ctx = ErrorContext(details={"file": "test.xml", "line": 42})
        ErrorHandler.handle(ConfigError("bad config"), context=ctx)

    def test_handle_with_custom_log_level(self):
        ErrorHandler.handle(InputError("warning"), log_level="warning")

    def test_classify_known_types(self):
        assert ErrorHandler._classify_error(FileNotFoundError()) == ErrorCategory.INPUT
        assert ErrorHandler._classify_error(ValueError()) == ErrorCategory.INPUT
        assert ErrorHandler._classify_error(BrokenPipeError()) == ErrorCategory.ENCODE
        assert ErrorHandler._classify_error(OSError()) == ErrorCategory.ENCODE
        assert ErrorHandler._classify_error(MemoryError()) == ErrorCategory.SYSTEM
        assert ErrorHandler._classify_error(PermissionError()) == ErrorCategory.ENCODE
        assert ErrorHandler._classify_error(RuntimeError()) == ErrorCategory.RENDER
        assert ErrorHandler._classify_error(KeyError()) == ErrorCategory.UNKNOWN

    def test_classify_subclass(self):
        assert ErrorHandler._classify_error(IsADirectoryError()) == ErrorCategory.INPUT


# =============================================================================
# handle_error
# =============================================================================

class TestHandleError:

    def test_basic(self):
        handle_error(ValueError("bad"), component="test")

    def test_with_all_params(self):
        handle_error(
            RenderError("fail"),
            component="renderer",
            operation="draw",
            frame_idx=99,
            extra="data",
        )