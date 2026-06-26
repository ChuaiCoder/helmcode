from __future__ import annotations


def parse_model_overrides(values: list[str] | None) -> dict[str, str]:
    if values is None or not isinstance(values, (list, tuple)):
        return {}
    overrides: dict[str, str] = {}
    for value in values:
        key, separator, model_id = value.partition("=")
        key = key.strip().lower()
        model_id = model_id.strip()
        if not separator or not key or not model_id:
            raise ValueError("model overrides must use KEY=provider:model")
        overrides[key] = model_id
    return overrides
