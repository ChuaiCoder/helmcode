from pathlib import Path

from helmcode.context.file_index import FileIndex
from helmcode.context.repo_map import RepoMap
from helmcode.context.workspace import Workspace


def test_file_index_reuses_persisted_cache_across_instances(tmp_path: Path) -> None:
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("content1")
    file2.write_text("content2")
    first_index = FileIndex(tmp_path)
    first_index.update_cache()

    file1.write_text("changed")
    second_index = FileIndex(tmp_path)

    assert second_index.get_changed_files() == ["file1.txt"]


def test_repo_map_incremental_rebuild_reuses_existing_index_cache(tmp_path: Path) -> None:
    (tmp_path / "file1.txt").write_text("content1")
    workspace = Workspace.discover(tmp_path)
    repo_map = RepoMap.build(workspace)
    repo_map.rebuild_incremental()

    (tmp_path / "file2.txt").write_text("content2")
    changed = repo_map.get_changed_files()

    assert changed == ["file2.txt"]
