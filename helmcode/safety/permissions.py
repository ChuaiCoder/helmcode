from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    READ_ONLY = "read_only"
    SUGGEST = "suggest"
    EDIT = "edit"
    AUTO = "auto"

    @classmethod
    def normalize(cls, value: str) -> "PermissionMode":
        return cls(value)

    @property
    def can_generate_patch(self) -> bool:
        return self in {self.SUGGEST, self.EDIT, self.AUTO}

    @property
    def can_apply_without_confirmation(self) -> bool:
        return self is self.AUTO
