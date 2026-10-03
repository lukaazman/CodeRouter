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

- `CodeRouter.py` - app window and run orchestration
- `model_router.py` - prompt classification and free model ranking
- `command_suggestions.py` - inline `/command` completions
- `ui_kit.py` - anti-aliased vector icons, tween animator, motion preference
- `history.py`, `permissions.py`, `model_health.py` - local history, permission ledger, model health
- `constants.py`, `run_types.py`, `redaction.py` - shared limits, data types, secret redaction

## Features

- Free-model fallback through OpenRouter
- Prompt-aware zero-credit routing with busy/unavailable fallback and local overrides
- Project scanning and optional read-only context
- Plan-first workflow with reviewable diffs
- Apply, reject, and undo file changes
- Bounded inspect and explicit local verification
- Local history and redacted task reports

## Interface

Flat dark workbench: icon rail, a top bar with project, phase stepper (Plan → Run → Review → Apply), model queue and next step, the conversation with a composer, and a collapsible Changes inspector. An empty conversation shows a small routing animation and prompt starters. Motion is subtle (progress line, phase pulse, sliding rail indicator, drawer slide) and can be turned off with **Reduce motion** in Settings (`"motion": "reduced"` in `local_config.json`, `"system"` to follow Windows animation settings). Below ~980 px the idle inspector folds away and the top bar compacts.

## Prompt-aware free routing

Each run classifies the prompt locally (coding, reasoning, math, writing, analysis, vision, translation, or general) and ranks OpenRouter models by category fit, context, and recent health.

Only explicitly free models are eligible: `:free`, `openrouter/free`, or catalog entries whose advertised pricing fields are all `0`. Busy, rate-limited, and unavailable providers are skipped in favor of the next free candidate.

## Inline command recommendations

The expanded local `/command` field shows a gray ghost completion chosen from the typed prefix, prompt category, and current workflow state. `Tab`, `→`, or clicking accepts it; `Esc` dismisses it. `Enter` submits only the command already typed.

OpenRouter references: [`:free` variant](https://openrouter.ai/docs/guides/routing/model-variants/free) · [`openrouter/free` router](https://openrouter.ai/docs/guides/routing/routers/free-router)
