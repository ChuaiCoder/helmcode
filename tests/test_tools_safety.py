from pathlib import Path

from helmcode.tools.read_file import ReadFileTool
from helmcode.tools.write_patch import WritePatchTool


def test_read_file_refuses_sensitive_files_by_default(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN=secret\n", encoding="utf-8")

    result = ReadFileTool(root_path=tmp_path).run({"path": ".env"})

    assert result.ok is False
    assert "Refusing" in result.content
    assert "secret" not in result.content


def test_write_patch_stores_pending_patch_without_applying(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello\n", encoding="utf-8")
    patch = """--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello world
"""

    result = WritePatchTool().run({"root_path": tmp_path, "patch": patch})

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert (tmp_path / ".helmcode" / "pending.patch").exists()
