from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip()


@dataclass(slots=True)
class Workspace:
    root_path: Path
    git_root: Path | None
    current_branch: str | None
    ignored_patterns: list[str] = field(default_factory=list)
    detected_languages: list[str] = field(default_factory=list)
    detected_frameworks: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    package_manager: str | None = None
    project_files_summary: str = ""

    @classmethod
    def discover(cls, path: str | Path) -> "Workspace":
        root = Path(path).resolve()
        git_root_text = _run_git(["rev-parse", "--show-toplevel"], root)
        git_root = Path(git_root_text).resolve() if git_root_text else None
        branch = _run_git(["branch", "--show-current"], root) if git_root else None

        ignored_patterns = _read_gitignore(root)
        languages, frameworks, test_commands, package_manager = _detect_project(root)
        summary = _project_summary(root, languages, frameworks, test_commands)

        return cls(
            root_path=root,
            git_root=git_root,
            current_branch=branch or None,
            ignored_patterns=ignored_patterns,
            detected_languages=languages,
            detected_frameworks=frameworks,
            test_commands=test_commands,
            package_manager=package_manager,
            project_files_summary=summary,
        )

    @property
    def is_git_repo(self) -> bool:
        return self.git_root is not None


def _read_gitignore(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return []
    return [
        line.strip()
        for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _detect_project(root: Path) -> tuple[list[str], list[str], list[str], str | None]:
    languages: set[str] = set()
    frameworks: set[str] = set()
    test_commands: list[str] = []
    package_manager: str | None = None

    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    if pyproject.exists() or requirements.exists() or any(root.glob("*.py")):
        languages.add("Python")
        package_manager = "uv" if (root / "uv.lock").exists() else "poetry" if (root / "poetry.lock").exists() else "pip"
        text = ""
        if pyproject.exists():
            text += pyproject.read_text(encoding="utf-8", errors="ignore").lower()
        if requirements.exists():
            text += "\n" + requirements.read_text(encoding="utf-8", errors="ignore").lower()
        if "pytest" in text or (root / "tests").exists():
            frameworks.add("pytest")
            test_commands.append("pytest")
        if "django" in text:
            frameworks.add("Django")
        if "fastapi" in text:
            frameworks.add("FastAPI")

    package_json = root / "package.json"
    if package_json.exists():
        languages.add("JavaScript")
        if (root / "tsconfig.json").exists():
            languages.add("TypeScript")
        package_manager = _node_package_manager(root)
        try:
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            package_data = {}
        deps = {
            **package_data.get("dependencies", {}),
            **package_data.get("devDependencies", {}),
        }
        scripts = package_data.get("scripts", {})
        if "react" in deps:
            frameworks.add("React")
        if "vue" in deps:
            frameworks.add("Vue")
        if "next" in deps:
            frameworks.add("Next.js")
        if "test" in scripts:
            test_commands.append(f"{package_manager or 'npm'} test")
        if "lint" in scripts:
            test_commands.append(f"{package_manager or 'npm'} run lint")
        if "typecheck" in scripts:
            test_commands.append(f"{package_manager or 'npm'} run typecheck")

    if (root / "go.mod").exists():
        languages.add("Go")
        package_manager = "go"
        test_commands.append("go test ./...")

    if (root / "Cargo.toml").exists():
        languages.add("Rust")
        package_manager = "cargo"
        test_commands.append("cargo test")

    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        languages.add("Java")
        package_manager = "maven" if (root / "pom.xml").exists() else "gradle"
        test_commands.append("mvn test" if package_manager == "maven" else "gradle test")

    return sorted(languages), sorted(frameworks), _dedupe(test_commands), package_manager


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _project_summary(
    root: Path,
    languages: list[str],
    frameworks: list[str],
    test_commands: list[str],
) -> str:
    notable = [
        name
        for name in [
            "pyproject.toml",
            "package.json",
            "go.mod",
            "Cargo.toml",
            "README.md",
            "tests",
            "src",
            "helmcode",
        ]
        if (root / name).exists()
    ]
    return (
        f"Languages: {', '.join(languages) or 'unknown'}; "
        f"Frameworks: {', '.join(frameworks) or 'unknown'}; "
        f"Tests: {', '.join(test_commands) or 'not detected'}; "
        f"Notable files: {', '.join(notable) or 'none'}"
    )
