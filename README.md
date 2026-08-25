# CodeRouter

CodeRouter is a local Windows desktop coding-agent workbench built with
Tkinter. It uses free OpenRouter models and keeps the user in control of file
changes through a reviewable diff.

## Current scope

- Choose a project folder and scan text context.
- Add extra read-only context files.
- Continue a coding conversation while the app keeps a bounded session history.
- Discover model metadata with a bounded metadata-only request, keep only explicitly free candidates, rank them by task context and coding signals, and retain the static known-free fallback order.
- Load the selected project root's bounded UTF-8 `AGENTS.md` plus a small deterministic hierarchy of relevant descendant `AGENTS.md` files as read-only project guidance; explicit depth, file, byte, containment, UTF-8, and secret/path guards skip unsafe candidates and report redacted run-scoped status.
- Generate a strict read-only execution plan first; plan output is streamed through the run timeline and the edit run cannot start until the user approves it, revises it, or cancels it.
- Stream the selected model response into a run-scoped append-only timeline, then assemble and validate the complete JSON before creating a proposal.
- Accept strict executor actions only as `final` or bounded read-only `inspect`;
  an inspect request is shown with explicit Allow/Deny controls, permits at
  most two bounded read rounds per task with a fresh isolated run per round,
  and never executes commands or writes files.
- Accept a separate bounded `verify` request that displays the proposed command
  with explicit Allow/Deny controls. Allow revalidates the exact command, root,
  parsed argv, and executable policy before starting the existing safe runner;
  at most one bounded, redacted result can start one continuation model request.
  The continuation remains review-first and cannot request a second verify round.
- Show the returned summary, activity log, changed files, and unified diff.
- Review and accept or reject pending edits.
- After a successful Apply, offer one explicit, in-memory Undo last apply action
  guarded by the selected root and post-apply file hashes; undo data is never
  persisted or sent to the overseer.
- Choose review-first or explicit auto-apply mode.
- Show task state for collection, model execution, review, apply, rejection,
  and errors.
- Keep path traversal and external-context write guards in the apply path.
- Persist bounded, redacted task metadata outside the repository at the
  user-local CodeRouter data path, with atomic writes and fail-closed recovery.
- Browse the bounded history newest-first in a compact metadata-only inspector;
  selecting a record is passive, and loading one for inspection still requires
  a fresh explicit plan before any edit run.
- Resume a selected historical task for inspection and request prefill only;
  resume never restores workers, proposals, file preconditions, or apply
  permission, and always requires a fresh explicit plan.
- Persist a stable bounded logical session id plus optional parent task/session
  links and bounded transitions; history resume restores metadata only and
  rejects invalid lineage records fail-closed.
- Own planning and edit workers plus active provider responses per run;
  reset, folder change, plan cancellation, and close signal cooperative
  cancellation and close registered responses without blocking the Tk thread.
- Run one bounded local verification command only from the visible manual
  control after the user types and confirms it. The runner uses an argv list
  with `shell=False`, the selected project root as its exact cwd, bounded
  output/timeout, a sanitized child environment, redacted run-scoped
  activity, and cooperative process-group cancellation. A small preset covers
  Python/py, Node, npm/pnpm, pytest, Cargo, dotnet, and git; unknown
  executables require a separate one-run policy approval. Shell wrappers are
  denied, and commands from model output, plans, `AGENTS.md`, history, and
  startup are never executed.
- Prepare a bounded, immutable Executor -> Overseer evidence handoff containing
  only redacted task metadata, changed-path counts, model/verification status,
  blockers, and acceptance evidence. Sending is terminal-gated and runs on a
  separate cancellable overseer worker using the explicitly-free model queue;
  an injected deterministic adapter is available for tests. The strict
  read-only JSON response is filtered before UI insertion. Sending evidence,
  preparing a next prompt, and running the next step are separate explicit
  user actions; Run next step creates a fresh planning snapshot and never
  starts the edit worker directly.
- Export one explicit, confirmation-gated JSON task report containing only
  bounded redacted metadata. The destination must be outside the selected
  project root; atomic failure preserves an existing destination, and report
  export never starts a worker, provider, command, proposal, Apply, or Undo.

## Roadmap

The next slices target the workflow patterns users expect from desktop coding
agents while keeping the app free and local:

1. Health, latency, and richer provider-availability signals around the free
   model selector.
2. Richer task timeline events and resumable streaming sessions.
3. Broader terminal/test tooling remains out of scope for the bounded
   verification runner and would require a separate explicit permission slice.
4. Integration with the separate overseer agent; the current local adapter is
   deterministic and never calls that agent automatically.
5. Broader project instruction sources beyond the bounded root/descendant
  secret/path handling.
   `AGENTS.md` hierarchy, hooks, and stronger secret/path handling.

## Configuration

Copy `local_config.example.json` to `local_config.json` and provide an
OpenRouter API key, or set `OPENROUTER_API_KEY`. `local_config.json` is local
configuration and must not be committed.

## Verification note

Static source checks and `git diff --check` are expected before each change.
Runtime behavior is claimed only when a direct Python 3.12 interpreter and
local Tk smoke provide evidence; local static tests do not prove provider
runtime behavior.

