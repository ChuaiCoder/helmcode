from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from helmcode.cli.main import app
from helmcode.context.context_builder import ContextBuilder
from helmcode.context.workspace import Workspace
from helmcode.memory.pinned_memory import PinnedMemoryStore, render_pinned_memory_for_context


def test_pinned_memory_store_adds_and_deletes_entries(tmp_path: Path) -> None:
    store = PinnedMemoryStore(tmp_path)

    first = store.add("Prefer quota routing for coding tasks.", entry_id="routing")
    second = store.add("Prefer quota routing for coding tasks.", entry_id="routing")

    assert first.id == "routing"
    assert second.id == "routing-2"
    assert [entry.id for entry in store.list()] == ["routing", "routing-2"]
    assert store.get("routing").text == "Prefer quota routing for coding tasks."
    assert store.delete("routing") is True
    assert [entry.id for entry in store.list()] == ["routing-2"]
    assert store.clear() == 1
    assert store.list() == []


def test_pinned_memory_refuses_secret_like_text(tmp_path: Path) -> None:
    store = PinnedMemoryStore(tmp_path)

    try:
        store.add("api_key=secret")
    except ValueError as exc:
        assert "looks sensitive" in str(exc)
    else:
        raise AssertionError("secret-like memory should be rejected")

    assert store.list() == []


def test_context_builder_injects_pinned_memory(tmp_path: Path) -> None:
    PinnedMemoryStore(tmp_path).add("Always inspect quota savings before changing routing.", entry_id="quota")
    workspace = Workspace.discover(tmp_path)

    built = ContextBuilder(workspace).build_for_task("change routing")

    assert "Pinned project memory:" in built.text
    assert "[quota] Always inspect quota savings" in built.text


def test_render_pinned_memory_limits_entries(tmp_path: Path) -> None:
    store = PinnedMemoryStore(tmp_path)
    store.add("first", entry_id="first")
    store.add("second", entry_id="second")

    rendered = render_pinned_memory_for_context(store.list(), limit=1)

    assert "[first] first" in rendered
    assert "second" not in rendered


def test_memory_cli_add_show_forget_and_clear(tmp_path: Path) -> None:
    runner = CliRunner()

    add = runner.invoke(
        app,
        ["memory", "add", "Prefer cheap scout before coder", "--id", "scout", "--workspace", str(tmp_path), "--json"],
    )
    assert add.exit_code == 0
    assert json.loads(add.output)["id"] == "scout"

    listing = runner.invoke(app, ["memory", "--workspace", str(tmp_path), "--json"])
    assert listing.exit_code == 0
    assert json.loads(listing.output)[0]["id"] == "scout"

    show = runner.invoke(app, ["memory", "show", "scout", "--workspace", str(tmp_path), "--json"])
    assert show.exit_code == 0
    assert json.loads(show.output)["text"] == "Prefer cheap scout before coder"

    forget = runner.invoke(app, ["memory", "forget", "scout", "--workspace", str(tmp_path), "--yes", "--json"])
    assert forget.exit_code == 0
    assert json.loads(forget.output)["deleted"] is True

    PinnedMemoryStore(tmp_path).add("another")
    clear = runner.invoke(app, ["memory", "clear", "--workspace", str(tmp_path), "--yes", "--json"])
    assert clear.exit_code == 0
    assert json.loads(clear.output)["removed"] == 1
