from __future__ import annotations

from pathlib import Path

from helmcode.memory.checkpoint_store import CheckpointStore


def test_checkpoint_store_restores_file_content(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("print('before')\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    checkpoint = store.create(label="before edit")

    target.write_text("print('after')\n", encoding="utf-8")
    result = store.restore(checkpoint.id)

    assert result.restored_files == ["app.py"]
    assert result.missing_files == []
    assert target.read_text(encoding="utf-8") == "print('before')\n"


def test_checkpoint_store_dry_run_does_not_restore(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("before\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    checkpoint = store.create()

    target.write_text("after\n", encoding="utf-8")
    result = store.restore(checkpoint.id, dry_run=True)

    assert result.dry_run is True
    assert result.restored_files == ["app.py"]
    assert target.read_text(encoding="utf-8") == "after\n"


def test_checkpoint_store_skips_sensitive_paths(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("code\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    checkpoint = CheckpointStore(tmp_path).create()

    assert "app.py" in checkpoint.files
    assert ".env" not in checkpoint.files
    assert any(item.startswith(".env: sensitive path") for item in checkpoint.skipped)


def test_checkpoint_store_can_restore_selected_path(tmp_path: Path) -> None:
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    first.write_text("a1\n", encoding="utf-8")
    second.write_text("b1\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    checkpoint = store.create()

    first.write_text("a2\n", encoding="utf-8")
    second.write_text("b2\n", encoding="utf-8")
    result = store.restore(checkpoint.id, paths=["a.py"])

    assert result.restored_files == ["a.py"]
    assert first.read_text(encoding="utf-8") == "a1\n"
    assert second.read_text(encoding="utf-8") == "b2\n"


def test_checkpoint_store_delete_removes_checkpoint(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("code\n", encoding="utf-8")
    store = CheckpointStore(tmp_path)
    checkpoint = store.create()

    assert [item.id for item in store.list()] == [checkpoint.id]
    assert store.delete(checkpoint.id) is True
    assert store.list() == []
