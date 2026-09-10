# CodeRouter
Desktop code agent wrapper similar to Codex and Claude Code, but using only Free AI models via OpenRouter.

## Features

- Free-model fallback through OpenRouter
- Prompt-aware zero-credit routing with busy/unavailable fallback and local overrides
- Project scanning and optional read-only context
- Plan-first workflow with reviewable diffs
- Apply, reject, and undo file changes
- Bounded inspect and explicit local verification
- Local history and redacted task reports

## Prompt-aware free routing

Each run classifies the prompt locally (coding, reasoning, math, writing, analysis, vision, translation, or general) and ranks OpenRouter models by category fit, context, and recent health.

Only explicitly free models are eligible: `:free`, `openrouter/free`, or catalog entries whose advertised pricing fields are all `0`. Busy, rate-limited, and unavailable providers are skipped in favor of the next free candidate.

## Inline command recommendations

The expanded local `/command` field shows a gray ghost completion chosen from the typed prefix, prompt category, and current workflow state. `Tab`, `→`, or clicking accepts it; `Esc` dismisses it. `Enter` submits only the command already typed.

OpenRouter references: [`:free` variant](https://openrouter.ai/docs/guides/routing/model-variants/free) · [`openrouter/free` router](https://openrouter.ai/docs/guides/routing/routers/free-router)
