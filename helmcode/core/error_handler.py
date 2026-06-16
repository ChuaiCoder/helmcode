from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any, Callable, TypeVar, Union

from helmcode.core.exceptions import (
    ConfigError,
    HelmcodeError,
    ModelError,
    PermissionDenied,
    ToolError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class ErrorResponse:
    success: bool
    error_type: str
    message: str
    details: dict[str, Any]
    suggestion: str | None = None
    traceback: str | None = None


class ErrorHandler:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self._error_map: dict[type, Callable[[Exception], ErrorResponse]] = {
            ConfigError: self._handle_config_error,
            ToolError: self._handle_tool_error,
            PermissionDenied: self._handle_permission_error,
            ModelError: self._handle_model_error,
            FileNotFoundError: self._handle_file_not_found,
            PermissionError: self._handle_permission_error,
            ConnectionError: self._handle_connection_error,
            TimeoutError: self._handle_timeout_error,
        }

    def handle(self, exc: Exception) -> ErrorResponse:
        handler = self._error_map.get(type(exc))
        if handler:
            response = handler(exc)
        else:
            response = self._handle_generic_error(exc)

        if self.verbose:
            response.traceback = traceback.format_exc()

        logger.error(
            "Error handled: type=%s message=%s",
            response.error_type,
            response.message,
        )
        return response

    def wrap(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> Union[T, ErrorResponse]:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            return self.handle(exc)

    def _handle_config_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="config_error",
            message=str(exc),
            details={"config_issue": True},
            suggestion="Check your configuration file at ~/.helmcode/config.yaml",
        )

    def _handle_tool_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="tool_error",
            message=str(exc),
            details={"tool_issue": True},
            suggestion="Verify the tool input parameters and try again",
        )

    def _handle_permission_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="permission_denied",
            message=str(exc),
            details={"permission_issue": True},
            suggestion="Check your permission mode settings or run with appropriate permissions",
        )

    def _handle_model_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="model_error",
            message=str(exc),
            details={"model_issue": True},
            suggestion="Verify your API key and model configuration",
        )

    def _handle_file_not_found(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="file_not_found",
            message=str(exc),
            details={"file_issue": True},
            suggestion="Check if the file path is correct and the file exists",
        )

    def _handle_connection_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="connection_error",
            message=str(exc),
            details={"network_issue": True},
            suggestion="Check your network connection and try again",
        )

    def _handle_timeout_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="timeout_error",
            message=str(exc),
            details={"timeout_issue": True},
            suggestion="The operation took too long. Try again or increase timeout settings",
        )

    def _handle_generic_error(self, exc: Exception) -> ErrorResponse:
        return ErrorResponse(
            success=False,
            error_type="unexpected_error",
            message=str(exc) or "An unexpected error occurred",
            details={"exception_type": type(exc).__name__},
            suggestion="If this persists, please report the issue",
        )


default_error_handler = ErrorHandler(verbose=False)


def handle_error(exc: Exception, verbose: bool = False) -> ErrorResponse:
    handler = ErrorHandler(verbose=verbose)
    return handler.handle(exc)


def safe_execute(func: Callable[..., T], *args: Any, verbose: bool = False, **kwargs: Any) -> Union[T, ErrorResponse]:
    handler = ErrorHandler(verbose=verbose)
    return handler.wrap(func, *args, **kwargs)