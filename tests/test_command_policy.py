from helmcode.safety.command_policy import CommandPolicy, CommandRisk


def test_command_policy_allows_safe_read_only_commands() -> None:
    result = CommandPolicy().check("pytest tests", permission_mode="edit")

    assert result.allowed is True
    assert result.risk == CommandRisk.LOW
    assert result.requires_confirmation is False


def test_command_policy_blocks_destructive_commands() -> None:
    result = CommandPolicy().check("rm -rf .", permission_mode="auto")

    assert result.allowed is False
    assert result.risk == CommandRisk.BLOCKED
    assert "rm -rf" in result.reason


def test_command_policy_requires_confirmation_for_publish() -> None:
    result = CommandPolicy().check("npm publish", permission_mode="auto")

    assert result.allowed is False
    assert result.requires_confirmation is True
    assert "publish" in result.reason
