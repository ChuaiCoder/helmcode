from pathlib import Path

import typer

from helmcode.cli.commands import apply as apply_command
from helmcode.cli.commands.apply import apply_pending_patch
from helmcode.core.constants import PENDING_PATCH_FILE, SESSION_DIR_NAME
from helmcode.core.exceptions import PermissionDenied


class RecordingSessionStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record(self, session_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((session_id, event_type, payload))


def _write_pending_patch(root: Path) -> str:
    (root / "hello.txt").write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""
    patch_dir = root / SESSION_DIR_NAME
    patch_dir.mkdir()
    (patch_dir / PENDING_PATCH_FILE).write_text(patch, encoding="utf-8")
    return patch


def test_apply_pending_patch_blocks_read_only_mode(tmp_path: Path) -> None:
    _write_pending_patch(tmp_path)

    try:
        apply_pending_patch(tmp_path, permission_mode="read_only", session_store=RecordingSessionStore())
    except PermissionDenied as exc:
        assert "read_only" in str(exc)
    else:
        raise AssertionError("read_only mode should not apply pending patches")

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert (tmp_path / SESSION_DIR_NAME / PENDING_PATCH_FILE).exists()


def test_apply_pending_patch_records_session_event(tmp_path: Path) -> None:
    _write_pending_patch(tmp_path)
    store = RecordingSessionStore()

    result = apply_pending_patch(tmp_path, permission_mode="suggest", session_store=store)

    assert result.applied_files == ["hello.txt"]
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hello world\n"
    assert not (tmp_path / SESSION_DIR_NAME / PENDING_PATCH_FILE).exists()
    assert store.events[0][1] == "patch_applied"
    assert store.events[0][2]["files"] == ["hello.txt"]


def test_apply_last_patch_preserves_no_pending_patch_exit_code(
    tmp_path: Path,
    monkeypatch,
) -> None:
    handled: list[Exception] = []

    def record_error(exc: Exception):
        handled.append(exc)
        raise AssertionError("typer.Exit should not be passed to the generic error handler")

    monkeypatch.setattr(apply_command.error_handler, "handle", record_error)

    try:
        apply_command.apply_last_patch(workspace=tmp_path, yes=True)
    except typer.Exit as exc:
        assert exc.exit_code == 1
    else:
        raise AssertionError("missing pending patch should exit")

    assert handled == []
