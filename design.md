# CodeRouter design system

CodeRouter is a local desktop workbench for running and reviewing free coding
agents. The interface should feel calm, dense, inspectable, and trustworthy:
the work is the visual focus, not decorative AI theatre.

## Product context

- **Audience:** software developers and technical users.
- **Primary use:** select a project, provide a task, inspect the proposed diff,
  and apply only the changes the user accepts.
- **Tone:** technical, utilitarian, calm.
- **Genre:** modern-minimal developer tool.
- **App structure:** Workbench — workspace controls on the left, task prompt and
  activity in the center, review inspector on the right.

## Visual rules

- Use semantic palette roles from the `PALETTE` dictionary in
  `codex_free_wrapper.py`; do not scatter new colour literals through widgets.
- Surfaces use a restrained dark neutral ladder: canvas, surface, raised
  surface, and terminal surface. Borders are thin and structural.
- Accent colour is reserved for focus, primary action, active selection, and
  the running state. Success, warning, and error colours communicate state;
  they are not decoration.
- No glow, gradient, animated background, oversized rounded card, fake browser
  chrome, or decorative AI imagery.
- Keep controls close to the object they affect. The right inspector is the
  source of truth for pending edits.
- Use Segoe UI for interface text and Consolas for prompts, logs, and diffs.
- Keep spacing on the 4/8/12/16/24 scale. Prefer alignment and separators over
  extra cards.

## Motion and interaction

- Feedback is immediate on press, selection, state change, and error.
- No motion is required to understand the workflow. Any future transition must
  animate only compositor-friendly properties and remain interruptible.
- Keyboard paths are first-class: Ctrl+Enter runs the prompt and Escape rejects
  pending changes.
- Focus, disabled, selected, and error states must remain visible without
  relying on colour alone.

## Task and permission model

The visible task states are `idle`, `collecting`, `planning`, `plan`,
`running`, `review`, `applied`, `rejected`,
and `error`. Every state is shown in the top bar and review inspector.

Review mode is the default. The model may propose complete file replacements,
but the user sees the diff before applying them. Auto-apply is explicit,
persisted per project, and still passes through root/path and external-context
guards. API keys and credential-shaped text must never enter the activity log,
summary, or session transcript.

After a successful transactional Apply, the workbench may retain exactly one
bounded in-memory undo transaction. Undo is a separate confirmed action,
requires an idle resource state and matching root/post-apply hashes, restores
the original missing/content state transactionally, and is cleared on reset,
folder change, or close. Undo metadata is not persisted or included in
history/evidence.

## Plan gate

Every new task enters an explicit planning phase before the edit worker. The
planning provider may return only strict JSON containing a summary and bounded
ordered steps. Its SSE chunks use the existing run-scoped, sequenced,
redacted timeline; a plan run cannot emit proposals, diffs, auto-apply events,
or write files.

The user must choose Approve plan, Revise, or Cancel. Approval creates a new
immutable run snapshot with the approved plan copied as read-only execution
context. The edit prompt receives that plan, but it never grants permissions,
overrides safety or path guards, or bypasses review/apply policy. Reset, folder
change, close, cancellation, malformed output, and credential-shaped output
invalidate or reject the pending plan.

## Read-only inspect permission

The edit executor accepts only strict `final` or `inspect` JSON actions. An
`inspect` action contains bounded relative paths only; absolute, traversal,
external-context, protected, and secret-like paths fail closed. The request is
shown in the review inspector and requires explicit Allow or Deny. Allow starts
exactly one bounded read-only round for the current run using the existing
collectors and redaction; Deny, stale decisions, cancellation, reset, folder
change, and close invalidate it. At most two rounds are allowed per task; each
Allow continuation receives a fresh run identity while preserving task/session
lineage. Inspect never runs commands, writes files, applies changes, or
auto-runs. A complete valid `final` response after Allow
may create the normal review proposal, which remains subject to existing
review-first and path/precondition guards.

## Verification request permission gate

The executor also accepts a strict `verify` action containing only one bounded
command string. The command is displayed as a proposal and requires explicit
Allow or Deny; model output never starts the existing local runner. Allow
revalidates the exact command, selected root, parsed argv, and executable policy,
then uses the existing safe runner. One bounded, redacted terminal result may
start exactly one continuation model request; the continuation remains
review-first and cannot request another verify round.

Stale decisions, cancellation, reset, folder change, close, blocked policy
input, and malformed or credential-shaped commands fail closed. The result is
metadata-only for UI/history/evidence; raw verification output is not retained.
No proposal, diff, apply, auto-apply, or file write is triggered by the runner
itself; a valid continuation final may create only the normal review proposal.

## Free-model selection

Model discovery sends metadata only. Candidates retain their free-proof source,
pricing metadata, optional context length, coding signals, and discovered or
static source. Paid or insufficiently verified candidates are rejected before
provider calls. Selection prefers a context window that fits the collected
task, then explicit coding signals, then stable identity/source ordering; the
known static free queue remains the final deterministic fallback. The selected
model and a short reason are emitted through the active run's status event.

## Streaming and timeline safety

Provider responses use bounded SSE streaming. Worker code incrementally parses
data chunks and emits redacted `stream_delta` events through the active
run-scoped queue; it never calls Tkinter. Events carry monotonic sequence
numbers, and the UI keeps an append-only run timeline for selection reasons,
fallback attempts, statuses, and streamed text. The complete response is
assembled and parsed before any proposal is created; streaming never writes
files incrementally.

## Read-only project instructions

At run creation, the workbench may read the selected root `AGENTS.md` plus a
small bounded set of relevant descendant `AGENTS.md` files. Descendants are
limited by explicit depth, file-count, per-file, and total-byte caps, sorted by
directory depth and relative path, and accepted only when their resolved path
remains inside the selected root. Symlink escapes, external paths, unreadable,
oversized, invalid UTF-8, empty, and secret-like candidates are skipped with a
redacted run-scoped status event. The root baseline is rendered first; nearer
directory scope precedes deeper scope, so later narrower sections are
deterministic context rather than authority.
The resulting text is copied into the immutable run snapshot and sent under a
clearly labeled read-only project-instructions section.

Project instructions are untrusted guidance. They cannot grant permissions,
override user safety rules, path guards, review/apply policy, or authorize
writes. `AGENTS.md` is protected from proposal paths, and external instruction
locations are not searched or loaded.

## Local task history and safe resume

History is a small metadata store under the user's local Windows application
data directory, not in the repository. Records are bounded and written with a
same-directory temporary file followed by replace. A corrupt, unreadable, or
oversized store is ignored so the workbench remains usable.

Persisted fields are limited to the project root, task id, bounded request and
plan summaries, plan steps, selected model, state transitions, fallback/status
reasons, outcome, and timestamps. API keys, bearer values, AGENTS.md content,
project files, diffs, streamed response text, pending proposals, and file
preconditions are never stored.

Resume is inspection-only. It may restore the recorded root, bounded request
summary, and read-only plan preview, but it never starts a worker, restores a
proposal, trusts old preconditions, applies changes, or resumes a live run.
Every resumed task must go through a new explicit plan and run before edits.

The sidebar history browser shows only a bounded newest-first list. Its
selection view exposes task id, timestamps, root availability, request and
plan metadata, selected model, outcome, and bounded transitions/reasons. A
selection changes no prompt, run, worker, proposal, precondition, or apply
state. The explicit load-for-inspection action may prefill the recorded root,
request, and read-only plan preview, but it remains inspection-only and cannot
start network work. The mutable history owner is detached before resume,
reset, folder change, or close so lifecycle cleanup cannot rewrite another
task's outcome.

## Worker and provider lifecycle

Each planning or edit run owns a cancellation event, its worker handle, and
any active provider response handle. Reset, folder change, plan revise/cancel,
and application close signal the event and request registered responses to
close. Workers check the run boundary before and after blocking/provider work,
unregister handles in `finally`, and can never produce usable stale events,
proposals, diffs, auto-apply events, or writes after invalidation. Shutdown is
bounded: the Tk thread does not join indefinitely on daemon workers. A close
request cannot interrupt an OS-level connection attempt until the socket call
returns; the next cancellation check then prevents further work.

## Bounded local verification permission boundary

The workbench exposes a restrained verification control separate from model
planning and edit workers. A command must be typed into that control and then
explicitly confirmed by the user; model output, an approved plan, root
`AGENTS.md`, saved history, and application startup cannot start it. The
control never invokes `cmd.exe`, PowerShell, or another shell wrapper. Input
is parsed into an argv list, rejects empty/invalid text and shell
metacharacters/redirection, and starts with `shell=False` only when the
selected project root exists and is the exact process cwd. The policy
allowlists a small developer preset (Python/py, Node, npm/pnpm, pytest, Cargo,
dotnet, and git); blocked shell wrappers fail closed, while an unknown
executable requires a distinct one-run policy approval before the normal run
confirmation.

The process has bounded combined output and timeout limits. Output is
redacted chunk-by-chunk before it enters the run-scoped sequenced timeline and
is not added to task history. The child receives only a bounded allowlisted
environment; API-key, token, secret, authorization, and bearer-shaped values
are excluded and environment values are never logged. The process handle
belongs to the verification run owner; reset, folder/context changes, New
Chat, close, and explicit Cancel request process-group termination without
waiting on the Tk thread. Windows uses a new process group and a best-effort
kill-on-close Job Object where available, followed by the existing short
terminate/kill grace window. The worker owns the cleanup and emits only
redacted start, output, exit, timeout, cancel, or error events. The runner
cannot create model proposals, diffs, apply events, or auto-apply writes.
Broader terminal and test-command execution remains a separate future
permission decision.

## Executor -> Overseer evidence boundary

The current handoff is an immutable, bounded in-memory record. It carries only
executor task/run identity, bounded request and plan metadata, relative changed
paths with add/delete counts, task outcome, model selection/health/fallback
statuses, verification status metadata, blockers, acceptance evidence, UTC
timestamps, and the observed run sequence. It never carries file contents,
diffs, streamed response text, raw verification output, API keys, bearer values,
or proposal preconditions.

Sending the handoff is a visible user action and is allowed only after the
executor reaches a terminal evidence state (`review`, `applied`, `rejected`, or
`error`) with no active executor worker or provider resource. The request runs
on a separate cancellable worker with its own run id and sequence, reusing the
explicitly-free model queue/provider resource ownership. A deterministic
adapter remains injectable for tests; no overseer call is automatic. Reset,
folder change, and close invalidate and cancel the overseer run.

Its response must be exact read-only JSON with `status`, `summary`, and a
bounded `next_step`. Responses containing secrets, edits, commands, permission
escalation, or auto-run instructions fail closed before queue/UI insertion. An
Approve next step only prepares bounded prompt metadata. A separate Run next
step action is required; it creates a fresh review-mode planning snapshot and
re-enters the plan approval gate. It never starts the edit worker directly,
executes a command, creates a proposal, or applies changes.
Reset, folder change, history resume, plan cancellation, context changes, and
close invalidate the handoff so stale evidence cannot be reviewed.

## Metadata-only session lineage

History records carry a bounded stable logical session_id and optional
parent_task_id/parent_session_id links. Plan-to-edit snapshots keep the same
session; an explicit Overseer continuation keeps that session and points to
its parent task. Verification child run ids are runtime resources, not new
user sessions. Legacy history without lineage fields derives a safe session id
from its task id; malformed, oversized, or credential-shaped lineage fields
are rejected.

Resume is inspection-only: it restores safe request/plan metadata, sets the
fresh-plan gate, clears workers, provider/verification/Overseer state,
proposals, and Undo, and never trusts old preconditions or starts execution.

## Safe task report export

The workbench exposes one visible `Export report` action only for a current
terminal task. The user selects a destination and confirms separately. The
export is a bounded JSON allowlist of task/run state, redacted transitions,
model/verification/Overseer metadata, counts, and root availability. It never
contains file contents, diffs, streamed or command output, credentials, or
in-memory Undo bytes. Destinations inside the selected project root are
rejected; writes use a temporary file plus atomic replace and leave an existing
destination untouched on failure. Export has no worker, network, command,
proposal, Apply, or history side effect.

## Executor and overseer flow

1. The executor collects the project snapshot and performs one bounded task.
2. CodeRouter shows model activity, changed files, and a diff.
3. The user accepts or rejects the proposed changes.
4. The overseer reviews the executor's evidence and sends the next bounded
   implementation or verification step.
5. The cycle repeats until the requested outcome is verified.

Future slices may add health/latency probes, richer resumable sessions, broader
local terminal/test tools, instruction sources beyond root `AGENTS.md`, and
richer safety policies. Each must preserve the review-first boundary.
