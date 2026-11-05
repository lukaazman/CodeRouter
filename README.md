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
- `extensions.py`, `plugins.py`, `ignore_rules.py` - skills, agents, output styles and plugins from disk; `.gitignore` rules
- `mcp_client.py`, `sandbox.py`, `web_fetch.py`, `context_budget.py` - MCP over stdio, network-off sandbox, `/fetch`, context budget
- `model_router.py` - prompt classification and free model ranking
- `command_suggestions.py` - inline `/command` completions
- `theme.py`, `ui_kit.py` - design tokens, icons, easing, timelines, motion preference
- `history.py`, `permissions.py`, `model_health.py` - local history, permission ledger, model health
- `constants.py`, `run_types.py`, `redaction.py` - shared limits, data types, secret redaction

## Features

- Free-model fallback through OpenRouter, prompt-aware routing
- Plan-first workflow (plan gate can be switched off), reviewable diffs
- Whole-file, search/replace and delete edits; apply, apply selected, reject, undo, `/rewind` up to 10 applies
- The model can `search` (regex, optional glob) and `list` folders locally, read-only, before it proposes changes
- Context skips files matched by `.gitignore` and `.coderouterignore`; projects over the budget (`context_budget_tokens`, default 60k) send a file tree plus the files most relevant to the prompt, and `/context` shows what fills the window
- Approval modes: **Suggest** (review everything), **Auto-edit** (apply edits, ask for reads and commands), **Full auto** (also allow reads and allow-listed commands). `Shift+Tab` in the composer or the status bar cycles them
- Persistent allow/deny rules: `Bash(pytest*)`, `Read(src/**)`, `Edit(docs/**)`, `Mcp(server.*)`; deny wins; **Always allow** on a request saves the rule
- MCP tool servers over stdio (see below)
- `/fetch <url>` adds a web page as read-only context; `/test` finds the test command; `/security-review`, `/pr-description`
- Memory: `AGENTS.md` hierarchy plus `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.override.md` and user files `~/.coderouter/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`. Start a prompt with `#` to save a note
- `@path` mentions with autocomplete; `/` autocomplete for every command
- Custom commands from `.claude/commands`, `.coderouter/commands`, `~/.claude/commands`, `~/.coderouter/commands`, `~/.codex/prompts` (`$ARGUMENTS`, `$1`..`$9`, `description:` frontmatter, folders become `ns:name`)
- Skills: `.claude/skills/<name>/SKILL.md`, `.coderouter/skills/…`, `~/.claude/skills/…`, `~/.codex/skills/…` join the context when the prompt matches their description; `/skill <name>` pins one
- Agents: `.claude/agents/<name>.md` (or `.coderouter/agents`) act as personas; `/agent <name>`, `/agent off`
- Output style files: `.claude/output-styles/<name>.md`; `/output-style <name>`
- Plugins: `~/.coderouter/plugins/<name>/` (or `.coderouter/plugins/` in a project) bundle `commands/`, `skills/`, `agents/`, `output-styles/`, `hooks.json` and `.mcp.json`; only user plugins may add hooks or MCP servers; `/plugins`, `/plugins disable <name>`
- Conversation transcript with plans shown as checklists; prompts typed during a run are queued
- Ask mode: start a prompt with `?` (or `/ask`) for an answer about the project with no plan and no edits
- Fuzzy command palette (`Ctrl+Shift+P`, `Ctrl+P` or `F1`); `Up`/`Down` recall earlier prompts
- `/code-review [base]` reviews the working tree (untracked files included) or a branch with a free model
- Saved conversations: `/resume`, `/sessions`, `/compact` summarises older turns, `/rename`, `/save` to Markdown, `/copy` the last reply
- Rings and marks the title when a plan, review or error is waiting while the window is in the background (`"notify": false` turns it off)
- Git: branch and changes in the status bar, `/git`, `/diff`, `/commit`
- Hooks: `SessionStart`, `UserPromptSubmit`, `PreToolUse` (MCP calls), `PostToolUse`, `PreApply`, `PostApply`, `Notification`, `Stop`; a non-zero exit from `UserPromptSubmit`, `PreToolUse` or `PreApply` blocks; argv only, no shell, JSON context on stdin
- Output style, reasoning effort and temperature per user; image attach for vision models
- Token and context meter (cost is always $0)
- Profiles: named setting sets in `"profiles"` switched with `/profile <name>`
- `"test_after_apply": true` runs the detected (or `"test_command"`) tests after each apply when an allow rule or Full auto permits it
- `"statusline_command": ["python", "tools/status.py"]` shows the first output line in the status bar (JSON context on stdin, every 10 s)
- Headless `exec` mode for scripts and CI
- Local history and redacted task reports

## Commands

`/help` `/ask <question>` `/doctor` `/status` `/model [auto|reset|<id>:free]` `/permissions` `/review` `/clear` `/compact [focus]` `/resume [id]` `/sessions` `/history` `/init` `/memory [add <note>]` `/diff [git]` `/apply` `/reject` `/undo` `/commit [message]` `/git` `/todos` `/cost` `/approval [mode]` `/allow <rule>` `/deny <rule>` `/style [name]` `/effort [level]` `/temperature [value]` `/theme [name]` `/motion [mode]` `/plan [on|off]` `/hooks` `/plugins` `/rules [remove <rule>]` `/sandbox [mode]` `/profile [name]` `/config` `/commands` `/export` `/verify [command]` `/add` `/image` `/mention <path>` `/code-review [base]` `/rewind [n]` `/skills` `/agents` `/output-style` `/models` `/mcp` `/fetch <url>` `/test` `/security-review` `/pr-description` `/restart` `/copy` `/save [file]` `/rename <title>` `/stop` `/exit`

Type them in the composer or the `Ctrl+K` command field. Shortcuts: `Ctrl+Enter` run, `Ctrl+K` command field, `Ctrl+Shift+P` / `F1` palette, `Ctrl+L` new chat, `Shift+Tab` approval mode, `Up`/`Down` prompt history, `Esc` cancel or close.

## Headless mode

```
python CodeRouter.py exec "add tests for the parser"
python CodeRouter.py exec --yes --no-plan "rename foo to bar in @src/util.py"
python CodeRouter.py exec -a full-auto --json "fix the failing test" > result.json
python CodeRouter.py exec --agent tester "cover the new parser"
python CodeRouter.py exec /review-pr 42
python CodeRouter.py commands
python CodeRouter.py ask "where is the config loaded?"
python CodeRouter.py -C ~/projects/api --resume
python CodeRouter.py "add a health check endpoint"
```

Without a subcommand, arguments open the window: `-C <folder>` opens a project, `--resume` restores its latest conversation, and any text is put in the composer.

Suggest mode prints the diff and exits with code 3 when changes are not applied; `--yes` or `--approval auto-edit` writes them. `exec`, `ask` and `commands` work without a display and even without Tkinter (servers, CI).

## Configuration

All keys are optional; see `local_config.example.json`: `approval_mode`, `plan_gate`, `style`, `reasoning_effort`, `temperature`, `theme` (`dark`, `light`, `system`), `accent` (any `#rrggbb`; hover and text colours are derived with safe contrast), `motion`, `notify`, `user_memory`, `permissions.allow/deny`, `hooks`, `profiles`, `mcp_servers`, `sandbox`, `context_budget_tokens`, `auto_commit`, `test_after_apply`, `test_command`, `statusline_command`, `plugins_disabled`. Conversations and history live in the per-user data folder (`%LOCALAPPDATA%\CodeRouter`, `~/.local/share/CodeRouter`, or `CODEROUTER_DATA_DIR`).

MCP (tools over stdio): add servers to `local_config.json` as `"mcp_servers": {"name": {"command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]}}` or to a project `.mcp.json` (`{"mcpServers": {"name": {"command": "…", "args": []}}}`). Project servers only start after `/mcp enable <name>`. The model calls tools with an `mcp` action; each call needs an `Mcp(server.tool)` allow rule or Full auto, otherwise it is refused and the model continues without it. `/mcp` shows servers and tools, `/mcp restart` reloads them.

Sandbox: `"sandbox": "network-off"` (or `/sandbox network-off`) runs verification and hook commands without network access, using `unshare -rn` on Linux or `sandbox-exec` on macOS; when neither exists the command is refused. Commands never run through a shell, only through the bounded, approved verification runner.

## Interface

Flat workbench in a warm dark or light theme: icon rail, a top bar with project, phase stepper (Plan → Run → Review → Apply), model queue and next step, the conversation with a composer, and a collapsible Changes inspector. An empty conversation shows a small routing animation and prompt starters. Motion uses one easing curve for UI steps and one for travel, with short durations (hover 140 ms, panels 200 ms) and staggered entrances (progress line, phase pulse, sliding rail indicator, drawer slide, toasts) and can be turned off with **Reduce motion** in Settings (`"motion": "reduced"` in `local_config.json`, `"system"` to follow Windows animation settings). Below ~980 px the idle inspector folds away and the top bar compacts.

## Prompt-aware free routing

Each run classifies the prompt locally (coding, reasoning, math, writing, analysis, vision, translation, or general) and ranks OpenRouter models by category fit, context, and recent health.

Only explicitly free models are eligible: `:free`, `openrouter/free`, or catalog entries whose advertised pricing fields are all `0`. Busy, rate-limited, and unavailable providers are skipped in favor of the next free candidate.

## Inline command recommendations

The expanded local `/command` field shows a gray ghost completion chosen from the typed prefix, prompt category, and current workflow state. `Tab`, `→`, or clicking accepts it; `Esc` dismisses it. `Enter` submits only the command already typed.

OpenRouter references: [`:free` variant](https://openrouter.ai/docs/guides/routing/model-variants/free) · [`openrouter/free` router](https://openrouter.ai/docs/guides/routing/routers/free-router)
