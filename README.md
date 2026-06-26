# helmcode

`helmcode` is a CLI-first local codebase Agent. It runs from a project directory, builds repo context through tools, plans before editing, writes changes as unified diffs, asks for confirmation before risky actions, and records observable local session events.

It is not a model routing product. Model discovery and role selection exist as lower-level plumbing; the main experience is helping with development tasks inside a local repository.

## Install

```bash
python -m pip install -e ".[dev]"
```

Then run:

```bash
helmcode setup
helmcode doctor
```

You can also install the CLI through npm. The npm package wraps the Python CLI
and creates a local virtual environment during install when Python 3.11+ is
available:

```bash
npm install -g .
helmcode setup
helmcode
```

For development without global install:

```bash
npm install
npx helmcode --version
```

Set `HELMCODE_SKIP_PYTHON_INSTALL=1` to skip npm postinstall Python setup, or
set `HELMCODE_PYTHON=/path/to/python` to force a specific interpreter.

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

You can generate this file from the CLI instead of editing YAML by hand:

```bash
helmcode setup \
  --provider-id main_pool \
  --base-url https://your-provider.example/v1 \
  --api-key-env MAIN_POOL_API_KEY \
  --model your-default-model \
  --fast-model your-fast-model \
  --planning-model your-planning-model \
  --coding-model your-coding-model \
  --review-model your-review-model \
  --coding-daily-limit 10
```

`setup` also writes model profiles, so Coding Plan allocation can distinguish
cheap scan/summarize calls from expensive coding calls.

## Common Commands

```bash
helmcode
helmcode chat
helmcode code --mode run --routing quota
helmcode init
helmcode setup
helmcode run "help me add tests for the auth module"
helmcode plan "explain this repository architecture"
helmcode models recommend "help me add tests for the auth module"
helmcode models status
helmcode agents plan "refactor the routing layer and add tests"
helmcode agents plan --json "refactor the routing layer and add tests"
helmcode checkpoint create "before risky refactor"
helmcode checkpoint restore <checkpoint-id> --dry-run
helmcode restore <checkpoint-id> --yes
helmcode sessions
helmcode events
helmcode stats
helmcode replay <session-id>
helmcode sessions diff <left-session-id> <right-session-id>
helmcode prune-sessions --keep 20
helmcode diff
helmcode apply
helmcode doctor
helmcode config
helmcode models sync
helmcode models list
helmcode models select coding main_pool:some-coding-model
```

Running `helmcode`, `helmcode chat`, or `helmcode code` starts an interactive
session. Bare text uses the current session mode, which defaults to `recommend`
so you can inspect model routing without spending provider quota. Use slash
commands to control the session:

```text
/recommend <task>             show model routing without calling a provider
/plan <task>                  generate a plan
/run <task>                   run plan, patch, review, apply confirmation, tests
/mode recommend|plan|run      set what bare prompt text does
/routing fixed|quota|recommend set model routing for the session
/model <provider:model|clear> force or clear a model override
/agents <task>                show quota-saving multi-agent assignment
/checkpoint [label]           create a local workspace checkpoint
/checkpoints                  list local checkpoints
/restore <id>                 restore a checkpoint after confirmation
/models                       show configured roles and profiles
/quota                        show local quota estimates
/sessions                     show recent local sessions
/events [session]             show recent audit events
/replay <session>             replay one session timeline
/session-diff <a> <b>         compare two sessions
/prune-sessions               delete old session records after confirmation
/stats                        show aggregate session stats
/status                       show workspace and routing status
/diff                         show pending patch
/apply                        apply pending patch
/doctor                       run local diagnostics
/init                         create AGENTS.md project instructions
/exit                         leave the session
```

`helmcode run` performs the main Agent workflow: generate a plan, ask whether to continue, generate a unified diff patch, show the diff, review the patch with the configured review model, ask whether to apply it, then run the detected test command unless `--no-tests` is passed. If tests fail, helmcode asks the coding model for a repair patch and retries verification up to three times. Use `--yes` for non-interactive approval of the plan and patch confirmations.

`helmcode init` creates a repo-scoped `AGENTS.md` with detected languages,
frameworks, test commands, and local agent workflow guidance. It refuses to
overwrite an existing file unless `--force` is passed. Use `--dry-run` to
preview the generated content.

`helmcode checkpoint create` stores a local snapshot of non-sensitive,
non-ignored workspace files under `.helmcode/checkpoints`. Use
`helmcode checkpoint restore <id> --dry-run` to preview a restore and
`helmcode restore <id> --yes` to restore captured files. Checkpoints skip paths
that look like secrets, such as `.env`, credentials, tokens, and private keys.

`helmcode agents plan` is a local Coding Plan allocation planner. It does not
call a provider. It splits a task across built-in agents such as `scout`,
`planner`, `coder`, `reviewer`, and `fixer`, then chooses models through the
quota-aware selector. This is useful for checking which work will use cheap
models and which work will spend coding-model quota before running the task.
Use `--json` when another tool or a future runtime loop needs to consume the
allocation directly.

Agent profiles can be extended in `~/.helmcode/config.yaml`. Triggered agents
are included when their trigger text appears in the task. If a triggered agent
has the same task type as an optional built-in agent, it replaces that optional
agent instead of adding a duplicate model call:

```yaml
agent_profiles:
  - id: security_reviewer
    role: review
    task_type: review
    model_role: review
    purpose: review security-sensitive code changes
    order: 45
    required: false
    triggers: ["security", "auth"]
```

## Permission Modes

`read_only`: read files, search code, and inspect git status only.

`suggest`: generate and review patches but do not apply them from `helmcode run`. This is the default. Use `helmcode diff` and `helmcode apply` to inspect and apply the pending patch. `helmcode apply` still refuses to run in `read_only` mode and records a local session event when it applies a patch.

`edit`: apply patches after user confirmation and run safe verification commands.

`auto`: may apply low-risk patches automatically. Destructive commands still require confirmation or are blocked.

## Safety Limits

The command policy blocks destructive commands such as `rm -rf`, `sudo`, recursive ownership or permission changes, `curl | sh`, `git reset --hard`, `git clean -fd`, `docker system prune`, `kubectl delete`, `terraform apply`, and database `drop` or `truncate` patterns.

Sensitive files such as `.env`, private keys, credentials, secrets, tokens, and cloud credentials are not read by default.

All file edits are represented as unified diffs. Pending patches are stored under `.helmcode/pending.patch` and can be inspected with `helmcode diff` before applying.

## Sessions And Audit Events

Every `plan` and `run` workflow records local session events under
`.helmcode/sessions.sqlite3` and `.helmcode/audit_log.jsonl`. Use these
commands to inspect what the agent selected, called, generated, applied, and
verified:

```bash
helmcode sessions
helmcode sessions --json
helmcode sessions events <session-id>
helmcode events --limit 20
helmcode replay <session-id>
helmcode sessions diff <left-session-id> <right-session-id>
helmcode prune-sessions --keep 20 --older-than-days 30
helmcode stats
helmcode stats --json
```

These commands are local-only and do not call a provider.

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
