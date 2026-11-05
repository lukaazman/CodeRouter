# CodeRouter
Desktop code agent wrapper similar to Codex and Claude Code, but using only Free AI models via OpenRouter.

## Setup

Requires Python 3.10+ with Tkinter (included in the python.org installers on Windows and macOS; on Linux install `python3-tk`). There are no other dependencies.

Run it:

- Windows: double-click `Run CodeRouter.bat`
- macOS / Linux: `./run.sh`

Sign in with OpenRouter from the app, or set `OPENROUTER_API_KEY`. Settings are saved to `local_config.json` next to the script (see `local_config.example.json`); it is gitignored.

Run the tests:

```
python -m unittest discover -s tests
```

## Layout

- `CodeRouter.py` - app window, run orchestration, provider calls
- `cli.py` - headless `exec` mode
- `slash_commands.py` - built-in and custom `/commands`
- `approval.py` - approval modes and allow/deny rules
- `memory_files.py`, `mentions.py`, `sessions.py` - memory files, `@file` mentions, saved conversations
- `git_tools.py`, `hooks.py`, `edit_ops.py`, `usage.py` - git, lifecycle hooks, search/replace edits, token meter
- `model_router.py` - prompt classification and free model ranking
- `command_suggestions.py` - inline `/command` completions
- `theme.py`, `ui_kit.py` - design tokens, icons, easing, timelines, motion preference
- `history.py`, `permissions.py`, `model_health.py` - local history, permission ledger, model health
- `constants.py`, `run_types.py`, `redaction.py` - shared limits, data types, secret redaction

## Features

- Free-model fallback through OpenRouter, prompt-aware routing
- Plan-first workflow (plan gate can be switched off), reviewable diffs
- Whole-file, search/replace and delete edits; apply, apply selected, reject, undo
- Approval modes: **Suggest** (review everything), **Auto-edit** (apply edits, ask for reads and commands), **Full auto** (also allow reads and allow-listed commands). `Shift+Tab` in the composer or the status bar cycles them
- Persistent allow/deny rules: `Bash(pytest*)`, `Read(src/**)`, `Edit(docs/**)`; deny wins
- Memory: `AGENTS.md` hierarchy plus `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.override.md` and user files `~/.coderouter/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`. Start a prompt with `#` to save a note
- `@path` mentions with autocomplete; `/` autocomplete for every command
- Custom commands from `.claude/commands`, `.coderouter/commands`, `~/.claude/commands`, `~/.coderouter/commands`, `~/.codex/prompts` (`$ARGUMENTS`, `$1`..`$9`, `description:` frontmatter, folders become `ns:name`)
- Saved conversations: `/resume`, `/sessions`, `/compact` summarises older turns
- Git: branch and changes in the status bar, `/git`, `/diff`, `/commit`
- Hooks: `UserPromptSubmit`, `PreApply` (non-zero exit blocks), `PostApply`, `Stop`; argv only, no shell
- Output style, reasoning effort and temperature per user; image attach for vision models
- Token and context meter (cost is always $0)
- Headless `exec` mode for scripts and CI
- Local history and redacted task reports

## Commands

`/help` `/status` `/model [auto|reset|<id>:free]` `/permissions` `/review` `/clear` `/compact [focus]` `/resume [id]` `/sessions` `/history` `/init` `/memory [add <note>]` `/diff [git]` `/apply` `/reject` `/undo` `/commit [message]` `/git` `/todos` `/cost` `/approval [mode]` `/allow <rule>` `/deny <rule>` `/style [name]` `/effort [level]` `/temperature [value]` `/theme [name]` `/motion [mode]` `/plan [on|off]` `/hooks` `/config` `/commands` `/export` `/verify [command]` `/add` `/image` `/stop` `/exit`

Type them in the composer or the `Ctrl+K` command field. Shortcuts: `Ctrl+Enter` run, `Ctrl+K` commands, `Ctrl+L` new chat, `Shift+Tab` approval mode, `Esc` cancel or close.

## Headless mode

```
python CodeRouter.py exec "add tests for the parser"
python CodeRouter.py exec --yes --no-plan "rename foo to bar in @src/util.py"
python CodeRouter.py exec -a full-auto --json "fix the failing test" > result.json
python CodeRouter.py exec /review-pr 42
python CodeRouter.py commands
```

Suggest mode prints the diff and exits with code 3 when changes are not applied; `--yes` or `--approval auto-edit` writes them. It needs Tkinter installed but no display.

## Configuration

All keys are optional; see `local_config.example.json`. `approval_mode`, `plan_gate`, `style`, `reasoning_effort`, `temperature`, `theme` (`dark`, `light`, `system`), `motion`, `user_memory`, `permissions.allow/deny`, `hooks`. Conversations and history live in the per-user data folder (`%LOCALAPPDATA%\CodeRouter`, `~/.local/share/CodeRouter`, or `CODEROUTER_DATA_DIR`).

Not supported: MCP servers and sandboxed shells; commands only run through the bounded, approved verification runner.

## Interface

Flat workbench in a warm dark or light theme: icon rail, a top bar with project, phase stepper (Plan → Run → Review → Apply), model queue and next step, the conversation with a composer, and a collapsible Changes inspector. An empty conversation shows a small routing animation and prompt starters. Motion uses one easing curve for UI steps and one for travel, with short durations (hover 140 ms, panels 200 ms) and staggered entrances (progress line, phase pulse, sliding rail indicator, drawer slide, toasts) and can be turned off with **Reduce motion** in Settings (`"motion": "reduced"` in `local_config.json`, `"system"` to follow Windows animation settings). Below ~980 px the idle inspector folds away and the top bar compacts.

## Prompt-aware free routing

Each run classifies the prompt locally (coding, reasoning, math, writing, analysis, vision, translation, or general) and ranks OpenRouter models by category fit, context, and recent health.

Only explicitly free models are eligible: `:free`, `openrouter/free`, or catalog entries whose advertised pricing fields are all `0`. Busy, rate-limited, and unavailable providers are skipped in favor of the next free candidate.

## Inline command recommendations

The expanded local `/command` field shows a gray ghost completion chosen from the typed prefix, prompt category, and current workflow state. `Tab`, `→`, or clicking accepts it; `Esc` dismisses it. `Enter` submits only the command already typed.

OpenRouter references: [`:free` variant](https://openrouter.ai/docs/guides/routing/model-variants/free) · [`openrouter/free` router](https://openrouter.ai/docs/guides/routing/routers/free-router)
