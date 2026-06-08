# helmcode

`helmcode` is a CLI-first local codebase Agent. It runs from a project directory, builds repo context through tools, plans before editing, writes changes as unified diffs, asks for confirmation before risky actions, and records observable local session events.

It is not a model routing product. Model discovery and role selection exist as lower-level plumbing; the main experience is helping with development tasks inside a local repository.

## Install

```bash
python -m pip install -e ".[dev]"
```

Then run:

```bash
helmcode doctor
```

## Configure A Provider

Create or edit `~/.helmcode/config.yaml`:

```yaml
permission_mode: suggest
providers:
  - id: main_pool
    type: openai_compatible
    base_url: https://your-provider.example/v1
    api_key_env: MAIN_POOL_API_KEY
model_roles:
  default: main_pool:your-default-model
  fast: main_pool:your-fast-model
  planning: main_pool:your-planning-model
  coding: main_pool:your-coding-model
  review: main_pool:your-review-model
```

Set the API key:

```bash
export MAIN_POOL_API_KEY=...
```

PowerShell:

```powershell
$env:MAIN_POOL_API_KEY="..."
```

## Common Commands

```bash
helmcode
helmcode run "help me add tests for the auth module"
helmcode plan "explain this repository architecture"
helmcode diff
helmcode apply
helmcode doctor
helmcode config
helmcode models sync
helmcode models list
helmcode models select coding main_pool:some-coding-model
```

`helmcode run` performs the main Agent workflow: generate a plan, ask whether to continue, generate a unified diff patch, show the diff, ask whether to apply it, then run the detected test command unless `--no-tests` is passed. If tests fail, helmcode asks the coding model for a repair patch and retries verification up to three times. Use `--yes` for non-interactive approval of the plan and patch confirmations.

## Permission Modes

`read_only`: read files, search code, and inspect git status only.

`suggest`: generate patches but do not apply them automatically. This is the default.

`edit`: apply patches after user confirmation and run safe verification commands.

`auto`: may apply low-risk patches automatically. Destructive commands still require confirmation or are blocked.

## Safety Limits

The command policy blocks destructive commands such as `rm -rf`, `sudo`, recursive ownership or permission changes, `curl | sh`, `git reset --hard`, `git clean -fd`, `docker system prune`, `kubectl delete`, `terraform apply`, and database `drop` or `truncate` patterns.

Sensitive files such as `.env`, private keys, credentials, secrets, tokens, and cloud credentials are not read by default.

All file edits are represented as unified diffs. Pending patches are stored under `.helmcode/pending.patch` and can be inspected with `helmcode diff` before applying.

## Example Tasks

```text
help me fix this bug
add unit tests for the auth module
refactor this function
find why login fails
change this API to return paginated results
explain this repository architecture
```

## Development Roadmap

The MVP includes CLI commands, workspace detection, repo map heuristics, tool abstractions, command policy, OpenAI-compatible providers, model roles, plan-first Agent loop, unified diff patch application, test command detection, and SQLite session event storage.

Planned follow-ups include deeper tool-calling loops, tree-sitter structure indexing, richer patch review, automated repair loops, IDE integration, and stronger long-context summarization. Web UI, cloud sync, multi-user support, complex quota scheduling, and automatic PR creation are intentionally out of scope for the first version.
