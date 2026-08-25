# CodeRouter Continuation Plan

Checkpoint: 2026-08-25 — Evidence-first Activity presentation complete and overseer-approved

The P0 resource-scope gate, compact workflow rail, CodeRouter window icon, model/queue disclosure, and evidence-first Activity slice are green and overseer-approved. Publication is controlled by the main task after approval; worker and overseer cycles do not commit or push.

## Current checkpoint

The current approved slice is the evidence-first Activity presentation, layered over the model/queue disclosure, compact workflow rail, bundled CodeRouter window icon, progressive-disclosure Workbench, and selective review/apply lifecycle:

- the compact single-line rail exposes `PHASE`, `MODEL-QUEUE`, and `NEXT` using the existing truthful task state, model status/health/fallback, and button/lifecycle gates;
- rail values do not invent model identity and the next-action text follows the existing user permissions and visible controls;
- `MODEL / QUEUE` is collapsed by default and expands on click, Return, or Space to show bounded redacted existing `model_status`, the deterministic free fallback queue, health metadata, and the active-run signal without changing model selection or provider logic;
- the compact always-visible Activity digest reports phase/run signal, bounded timeline event count, permission-decision count, error/blocker count, and a safe last-evidence label;
- the existing append-only Activity disclosure and log remain the source of truth; expanding/collapsing preserves the existing widget, content, scroll state, and callbacks;
- digest values are bounded, redacted metadata only and never expose raw stream/command output or secrets; the presentation adds no worker, provider, process, proposal, apply, or other execution side effect;
- History, Manual verification, Activity, and Task tools are collapsed by default;
- project/task controls, prompt, compact summary/status, review state, changed-file list/diff, and primary review actions remain visible;
- the Task tools disclosure contains plan, read-only inspect, verification request, and Executor -> Overseer handoff controls;
- active plan, inspect, verification, running work, and ready/active handoff state auto-opens the relevant disclosure;
- active permission actions cannot be hidden, and disclosure toggles preserve existing widgets, text, selection, callbacks, and state through non-destructive grid visibility changes;
- `_update_apply_controls()` refreshes the rail after Apply, Apply selected, and Reject button states are finalized, preventing a stale `Ready` signal when review actions are enabled;
- `assets/code-router.svg` is bundled and matches `C:\Users\Luka\Documents\GitHub\Portfolio\assets\projects\code-router.svg` byte-identically;
- the bundled mark is applied through a dependency-free 32x32 Tk `PhotoImage` retained on the app instance, with fail-closed behavior when icon setup is unavailable;
- selective review/apply remains multi-file, transactional, review-gated, and preserves unselected edits as pending work;
- partial Apply -> Undo returns to REVIEW only for a non-empty same-run accepted pending proposal, while full Apply Undo remains IDLE.

The broader implementation already includes the dark Workbench shell, free-model discovery and fallback queue, capability-aware model selection, streaming timeline, project instructions, plan approval, safe inspect/verify loops, executor-to-overseer evidence handoff, continuation gates, permission ledger, task export, session lineage, command palette, and bounded Undo.

## Current verified evidence

- Focused Activity, model/queue disclosure, workflow-rail, progressive-disclosure, and lifecycle checks: `Ran 27 tests ... OK`.
- Full suite: three consecutive runs, each `Ran 236 tests ... OK`, with no unexpected warnings.
- `python -m py_compile .\\codex_free_wrapper.py`: exit `0`.
- Activity smoke: `APP_SMOKE_OK True 'ACTIVITY ... events=0 ... permissions=0 ... errors/blockers=0 ... last=none' False; ACTIVITY_OPEN True True; APP_DESTROY_OK True True`.
- Asset verification: `assets/code-router.svg` hash matches the Portfolio source byte-for-byte.
- `git diff --check`: exit `0`; only standard LF-to-CRLF notices.

## P0 resource-scope fix

The active-resource checks are now run-scoped:

1. Include the current proposal/lifecycle run and its linked verification/overseer child runs.
2. Ignore unrelated stale run IDs from previous runs.
3. Keep blocking genuinely active current workers, provider responses, and processes.
4. Apply the same scope rule consistently to normal Apply, `Apply selected`, and Undo.
5. Preserve stale-event filtering and cleanup behavior; do not solve this by weakening lifecycle safety or clearing registries globally.
6. Add a regression proving that an old stale handle does not block the current Apply while a current-run handle still blocks it.

The former global `_undo_has_active_resources()` check was replaced with the same scoped helper.

## Current continuation status

The selective-apply lifecycle closeout, progressive-disclosure shell, compact workflow rail, CodeRouter window icon, model/queue disclosure, and evidence-first Activity presentation are complete and overseer-approved. Partial Apply -> Undo returns to REVIEW only for a non-empty same-run accepted pending proposal; full Apply Undo remains IDLE; remaining Apply stays transactional. The rail, model/queue disclosure, and Activity digest are UI-only metadata views, the bundled icon has no runtime Portfolio-path dependency, and all preserve existing safety, worker, overseer, and lifecycle boundaries.

## Next bounded roadmap

Proceed autonomously in this order, one bounded slice at a time:

1. Review inspector refinement.
2. Settings/trust surfaces.

Each slice must preserve the current primary workflow and may not expand into a new provider, command, persistence, or permission capability unless explicitly assigned.

## Worker / executor instructions

On continuation, the worker must:

1. Read this file and inspect the current uncommitted diff before editing.
2. Take exactly one item from the Next bounded roadmap and keep the patch limited to that slice and its focused regression tests.
3. Reuse existing UI, lifecycle, lineage, resource, permission, history, proposal, apply/undo, worker, and Overseer helpers; do not invent a second run-id system or weaken any guard.
4. Preserve review-first behavior, plan/inspect/verification gates, root/path safety, cancellation, stale-event filtering, redaction, transactional rollback, and no-Tk-from-worker behavior.
5. Run the focused slice tests, the full suite, compile, Tk/app smoke, and `git diff --check`; report exact results and any provider/OS limitation.
6. Return a concise handoff containing changed files, evidence, remaining risks, and one next bounded action.
7. Do not commit or push. Only the main task may commit/push after overseer approval.

Required commands from the repository root:

```powershell
python -m unittest tests.test_task_history.TaskHistoryUiTests.test_plan_review_apply_reject_error_reset_and_close_are_recorded -q
python -m unittest tests.test_selective_apply tests.test_apply_undo tests.test_proposal_lifecycle -q
python -m py_compile .\codex_free_wrapper.py
python -m unittest discover -s tests -q
python -m unittest discover -s tests -q
python -m unittest discover -s tests -q
git diff --check
```

The existing Tk and application smoke commands should be reused from the test/debug helpers already present in the repository; report their exact result rather than claiming runtime proof from compilation.

## Overseer instructions

The overseer reviews one bounded roadmap slice at a time and must:

1. Review the worker diff before accepting it.
2. Confirm the slice changes only its approved surface and preserves review-first behavior, explicit permission decisions, stale-event filtering, cancellation, rollback, resource cleanup, and worker/Overseer isolation.
3. Confirm focused tests, the full suite, compile, Tk/app smoke, and diff-check provide exact evidence.
4. Return `approved` only when all gates are green. Otherwise return `needs_attention` with one concrete bounded correction for the worker.
5. Do not expand the roadmap, add a new capability, or authorize unrelated work in the same slice.
6. Commit/push decisions belong only to the main task after approval; worker and overseer do not publish changes.

## Continuation protocol

Every worker cycle follows this order:

`read handoff -> inspect diff -> one bounded roadmap slice -> focused tests -> full gates -> overseer review -> next bounded slice`

The main task routes implementation work to the worker and evidence/review work to the overseer. After approval, the next cycle starts with the next roadmap item and does not reopen completed slices.

## Known boundaries

- No live provider/OpenRouter runtime claim is required for this checkpoint; mocked/local verification is sufficient.
- Publication is controlled by the main task after approval; preserve existing changes and never reset or discard unrelated work.
- Do not include raw project files, raw diffs, or stream bodies in task history, handoffs, exports, or permission metadata.
