from __future__ import annotations

from pathlib import Path
import json

from typer.testing import CliRunner

from helmcode.cli.commands import doctor
from helmcode.cli.main import app
from helmcode.context.workspace import Workspace
from helmcode.core.config import HelmcodeConfig, ProviderConfig


def test_build_doctor_checks_is_local_by_default(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "helmcode.js").write_text("#!/usr/bin/env node\n", encoding="utf-8")
    config = HelmcodeConfig(
        providers=[
            ProviderConfig(
                id="main_pool",
                base_url="https://example.com/v1",
                api_key_env="MISSING_POOL_API_KEY",
            )
        ],
        model_roles={"planning": "main_pool:planner"},
    )

    checks = doctor.build_doctor_checks(
        Workspace.discover(tmp_path),
        config,
        probe_models=False,
    )
    by_name = {check.name: check for check in checks}

    assert by_name["helmcode npm wrapper"].ok is True
    assert by_name["package manifest"].ok is True
    assert by_name["API keys"].ok is False
    assert "MISSING_POOL_API_KEY" in by_name["API keys"].details
    assert by_name["model reachability"].ok is True
    assert "skipped" in by_name["model reachability"].details


def test_parse_ahead_from_git_branch_line() -> None:
    assert doctor._parse_ahead("## main...origin/main [ahead 4]") == 4
    assert doctor._parse_ahead("## main...origin/main") == 0


def test_doctor_json_output_is_machine_readable(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "helmcode.js").write_text("#!/usr/bin/env node\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path), "--json"])

    assert result.exit_code == 0
    assert "Checking environment" not in result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
