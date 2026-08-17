"""统一错误处理策略

定义项目中的错误类型、恢复策略和错误处理器。
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
# 恢复策略
# =============================================================================

class RecoveryAction(enum.Enum):
    """错误恢复策略"""
    RETRY = "retry"
    SKIP = "skip"
    RESTART = "restart"
    ABORT = "abort"
    IGNORE = "ignore"


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
        recovery: RecoveryAction = RecoveryAction.ABORT,
        context: ErrorContext | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.recovery = recovery
        self.context = context or ErrorContext()


class InputError(DanmakuProError):
    """输入错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(
            message, category=ErrorCategory.INPUT,
            recovery=RecoveryAction.ABORT, context=context,
        )


class ConfigError(DanmakuProError):
    """配置错误"""
    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(
            message, category=ErrorCategory.CONFIG,
            recovery=RecoveryAction.ABORT, context=context,
        )


class RenderError(DanmakuProError):
    """渲染错误"""
    def __init__(
        self, message: str,
        recovery: RecoveryAction = RecoveryAction.SKIP,
        context: ErrorContext | None = None,
    ):
        super().__init__(
            message, category=ErrorCategory.RENDER,
            recovery=recovery, context=context,
        )


class EncodeError(DanmakuProError):
    """编码错误"""
    def __init__(
        self, message: str,
        recovery: RecoveryAction = RecoveryAction.RESTART,
        context: ErrorContext | None = None,
    ):
        super().__init__(
            message, category=ErrorCategory.ENCODE,
            recovery=recovery, context=context,
        )


class ResourceError(DanmakuProError):
    """资源错误"""
    def __init__(
        self, message: str,
        recovery: RecoveryAction = RecoveryAction.SKIP,
        context: ErrorContext | None = None,
    ):
        super().__init__(
            message, category=ErrorCategory.RESOURCE,
            recovery=recovery, context=context,
        )


# =============================================================================
# 错误处理器
# =============================================================================

class ErrorHandler:
    """统一错误处理器"""

    _stats: dict[ErrorCategory, int] = {}

    @classmethod
    def handle(
        cls, error: Exception,
        context: ErrorContext | None = None,
        log_level: str = "error",
    ) -> RecoveryAction:
        """处理错误，返回恢复策略"""
        context = context or ErrorContext()

        if isinstance(error, DanmakuProError):
            category = error.category
            recovery = error.recovery
            message = str(error)
        else:
            category, recovery = cls._classify_error(error)
            message = f"[{category.value}] {str(error)}"

        cls._stats[category] = cls._stats.get(category, 0) + 1

        log_func = getattr(logger, log_level)
        log_func(
            f"{message} | component={context.component}, "
            f"operation={context.operation}, frame={context.frame_idx}"
        )

        if context.details:
            logger.debug(f"错误详情: {context.details}")

        return recovery

    @classmethod
    def _classify_error(cls, error: Exception) -> tuple[ErrorCategory, RecoveryAction]:
        """根据异常类型分类"""
        if isinstance(error, (FileNotFoundError, IsADirectoryError, ValueError)):
            return ErrorCategory.INPUT, RecoveryAction.ABORT
        if isinstance(error, (BrokenPipeError, OSError)):
            return ErrorCategory.ENCODE, RecoveryAction.RESTART
        if isinstance(error, (MemoryError, PermissionError)):
            return ErrorCategory.SYSTEM, RecoveryAction.ABORT
        if isinstance(error, RuntimeError):
            return ErrorCategory.RENDER, RecoveryAction.SKIP
        return ErrorCategory.UNKNOWN, RecoveryAction.ABORT


# =============================================================================
# 便捷函数
# =============================================================================

def handle_error(
    error: Exception,
    component: str | None = None,
    operation: str | None = None,
    frame_idx: int | None = None,
    **details: Any,
) -> RecoveryAction:
    """便捷的错误处理函数"""
    context = ErrorContext(
        component=component, operation=operation,
        frame_idx=frame_idx,
        details=details if details else None,
    )
    return ErrorHandler.handle(error, context)