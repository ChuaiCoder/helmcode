from helmcode.models.selector import ModelSelector


def test_model_selector_uses_role_model() -> None:
    selector = ModelSelector(
        model_roles={
            "default": "main:gpt-default",
            "coding": "main:gpt-code",
        }
    )

    assert selector.select("coding") == "main:gpt-code"


def test_model_selector_falls_back_to_default_role() -> None:
    selector = ModelSelector(model_roles={"default": "main:gpt-default"})

    assert selector.select("review") == "main:gpt-default"
