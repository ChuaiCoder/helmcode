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


def test_command_policy_blocks_database_drop() -> None:
    result = CommandPolicy().check("psql -c 'drop table users'", permission_mode="auto")

    assert result.allowed is False
    assert result.risk == CommandRisk.BLOCKED


def test_command_policy_allows_read_only_git_commands_in_read_only_mode() -> None:
    for command in [
        "git status",
        "git diff",
        "git log --oneline",
        "git show HEAD",
        "git branch --show-current",
        "git rev-parse --show-toplevel",
    ]:
        result = CommandPolicy().check(command, permission_mode="read_only")

        assert result.allowed is True, command
        assert result.risk == CommandRisk.LOW


def test_command_policy_still_blocks_destructive_git_commands() -> None:
    for command in ["git reset --hard", "git clean -fd"]:
        result = CommandPolicy().check(command, permission_mode="auto")

        assert result.allowed is False, command
        assert result.risk == CommandRisk.BLOCKED
