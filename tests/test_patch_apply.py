from pathlib import Path

from helmcode.patch.apply import PatchApplyError, apply_unified_patch
from helmcode.patch.parser import PatchParser


def test_patch_parser_validates_unified_diff() -> None:
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""

    parsed = PatchParser().parse(patch)

    assert parsed.files == ["hello.txt"]


def test_apply_unified_patch_changes_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""

    result = apply_unified_patch(tmp_path, patch)

    assert result.applied_files == ["hello.txt"]
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_apply_unified_patch_rejects_context_mismatch(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("different\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""

    try:
        apply_unified_patch(tmp_path, patch)
    except PatchApplyError as exc:
        assert "context" in str(exc).lower()
    else:
        raise AssertionError("patch with mismatched context should fail")
