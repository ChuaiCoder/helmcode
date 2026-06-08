from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


SENSITIVE_NAME_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"(^|/)\.env(\..*)?$",
        r"id_rsa$",
        r"id_ed25519$",
        r"credentials",
        r"secrets?",
        r"token",
        r"private[_-]?key",
        r"cloud.*credentials",
    ]
]


@dataclass(slots=True)
class SecretScanResult:
    sensitive: bool
    reason: str = ""


class SecretScanner:
    def check_path(self, path: str | Path) -> SecretScanResult:
        text = Path(path).as_posix()
        for pattern in SENSITIVE_NAME_PATTERNS:
            if pattern.search(text):
                return SecretScanResult(True, f"sensitive path pattern: {pattern.pattern}")
        return SecretScanResult(False, "")

    def redact_env_values(self, content: str) -> str:
        redacted: list[str] = []
        for line in content.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _value = line.split("=", 1)
                redacted.append(f"{key}=<redacted>")
            else:
                redacted.append(line)
        return "\n".join(redacted)
