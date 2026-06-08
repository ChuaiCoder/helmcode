from __future__ import annotations

from dataclasses import dataclass

from helmcode.core.constants import MODEL_ROLE_DEFAULT
from helmcode.core.exceptions import ModelError


@dataclass(slots=True)
class ModelSelector:
    model_roles: dict[str, str]

    def select(self, role: str) -> str:
        model_id = self.model_roles.get(role) or self.model_roles.get(MODEL_ROLE_DEFAULT)
        if not model_id:
            raise ModelError(
                f"No model configured for role {role!r} and no {MODEL_ROLE_DEFAULT!r} fallback is set"
            )
        return model_id
