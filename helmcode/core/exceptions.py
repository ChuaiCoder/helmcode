from __future__ import annotations


class HelmcodeError(Exception):
    """Base exception for expected helmcode failures."""


class ConfigError(HelmcodeError):
    """Raised when configuration is invalid or incomplete."""


class ToolError(HelmcodeError):
    """Raised when a tool cannot complete its work."""


class PermissionDenied(HelmcodeError):
    """Raised when a command or file action is blocked by policy."""


class ModelError(HelmcodeError):
    """Raised when provider calls or model selection fail."""
