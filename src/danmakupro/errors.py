"""统一错误处理

定义项目中的错误类型和错误处理器。所有错误均终止任务。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from loguru import logger


# =============================================================================
# 错误分类
# =============================================================================

class ErrorCategory(enum.Enum):
    """错误分类"""
    INPUT = "input"
    CONFIG = "config"
    RENDER = "render"
    ENCODE = "encode"
    RESOURCE = "resource"
    SYSTEM = "system"
    UNKNOWN = "unknown"


# =============================================================================
# 错误上下文
# =============================================================================

@dataclass
class ErrorContext:
    """错误上下文信息"""
    frame_idx: int | None = None
    task_id: str | None = None
    component: str | None = None
    operation: str | None = None
    details: dict[str, Any] | None = None


# =============================================================================
# 自定义异常
# =============================================================================

class DanmakuProError(Exception):
    """项目基础异常"""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        context: ErrorContext | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.context = context or ErrorContext()


class InputError(DanmakuProError):
    """输入错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message, category=ErrorCategory.INPUT, context=context)


class ConfigError(DanmakuProError):
    """配置错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message, category=ErrorCategory.CONFIG, context=context)


class RenderError(DanmakuProError):
    """渲染错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message, category=ErrorCategory.RENDER, context=context)


class EncodeError(DanmakuProError):
    """编码错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message, category=ErrorCategory.ENCODE, context=context)


class ResourceError(DanmakuProError):
    """资源错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message, category=ErrorCategory.RESOURCE, context=context)


# =============================================================================
# 错误处理器
# =============================================================================

class ErrorHandler:
    """统一错误处理器"""

    @classmethod
    def handle(
        cls,
        error: Exception,
        context: ErrorContext | None = None,
        log_level: str = "error",
    ) -> None:
        """记录错误并抛出，终止当前任务。"""
        context = context or ErrorContext()

        if isinstance(error, DanmakuProError):
            category = error.category
            message = str(error)
        else:
            category = cls._classify_error(error)
            message = f"[{category.value}] {str(error)}"

        log_func = getattr(logger, log_level)
        log_func(
            f"{message} | component={context.component}, "
            f"operation={context.operation}, frame={context.frame_idx}"
        )

        if context.details:
            logger.debug(f"错误详情: {context.details}")

        raise error

    @classmethod
    def _classify_error(cls, error: Exception) -> ErrorCategory:
        """根据异常类型分类"""
        if isinstance(error, (FileNotFoundError, IsADirectoryError, ValueError)):
            return ErrorCategory.INPUT
        if isinstance(error, (BrokenPipeError, OSError)):
            return ErrorCategory.ENCODE
        if isinstance(error, (MemoryError, PermissionError)):
            return ErrorCategory.SYSTEM
        if isinstance(error, RuntimeError):
            return ErrorCategory.RENDER
        return ErrorCategory.UNKNOWN


# =============================================================================
# 便捷函数
# =============================================================================

def handle_error(
    error: Exception,
    component: str | None = None,
    operation: str | None = None,
    frame_idx: int | None = None,
    **details: Any,
) -> None:
    """记录错误并抛出，终止当前任务。"""
    context = ErrorContext(
        component=component,
        operation=operation,
        frame_idx=frame_idx,
        details=details if details else None,
    )
    ErrorHandler.handle(error, context)