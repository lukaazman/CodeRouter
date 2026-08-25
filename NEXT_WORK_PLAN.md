# CodeRouter Continuation Plan

Checkpoint: 2026-08-25 — Trust & settings disclosure complete and verified

The P0 resource-scope gate, compact workflow rail, CodeRouter window icon, model/queue disclosure, evidence-first Activity, review-inspector refinement, and Trust & settings slices are green and verified. Publication is controlled by the main task after approval; worker and overseer cycles do not commit or push.

## Current checkpoint

The current completed slice is the Trust & settings disclosure, layered over the review-inspector refinement, evidence-first Activity presentation, model/queue disclosure, compact workflow rail, bundled CodeRouter window icon, progressive-disclosure Workbench, and selective review/apply lifecycle:

- the compact single-line rail exposes `PHASE`, `MODEL-QUEUE`, and `NEXT` using the existing truthful task state, model status/health/fallback, and button/lifecycle gates;
- rail values do not invent model identity and the next-action text follows the existing user permissions and visible controls;
- `MODEL / QUEUE` is collapsed by default and expands on click, Return, or Space to show bounded redacted existing `model_status`, the deterministic free fallback queue, health metadata, and the active-run signal without changing model selection or provider logic;
- the compact always-visible Activity digest reports phase/run signal, bounded timeline event count, permission-decision count, error/blocker count, and a safe last-evidence label;
- the existing append-only Activity disclosure and log remain the source of truth; expanding/collapsing preserves the existing widget, content, scroll state, and callbacks;
- digest values are bounded, redacted metadata only and never expose raw stream/command output or secrets; the presentation adds no worker, provider, process, proposal, apply, or other execution side effect;
- the review inspector keeps the existing Treeview/diff and shows compact `selected/total · inspecting relative-path` metadata near the changed-file list, with a bounded empty state;
- the metadata refreshes on populate, clear, and extended selection while the first selected file continues to drive the inspected diff;
- Treeview identity, multi-selection, diff behavior, `Apply selected`, and transactional review/apply behavior remain unchanged;
- the compact `Trust & settings` disclosure sits between the visible Apply Policy controls and Actions without hiding or changing the Review changes, Auto-apply, permission note, Apply, Reject, or Undo safety controls;
- Trust & settings is collapsed by default and expands on click, Return, or Space using non-destructive `grid`/`grid_remove` visibility; it shows only bounded redacted apply mode/permission note, active RunSnapshot project-instructions status, PermissionDecisionLedger count/last safe label, and the existing local-command user-action-only policy reminder;
- a current inspect or verification permission request auto-opens Trust & settings and keeps it open, while ordinary idle/active snapshots remain manually collapsible; the surface performs no worker, provider, process, proposal, apply, persistence, or permission-authority action;
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

- Focused Trust & settings checks: `Ran 5 tests in 0.761s ... OK`.
- Focused Trust & settings plus review-inspector, Activity, model/queue disclosure, workflow-rail, progressive-disclosure, and lifecycle checks: `Ran 37 tests in 4.161s ... OK`.
- Full suite: three consecutive runs, `Ran 246 tests in 13.735s`, `Ran 246 tests in 14.048s`, and `Ran 246 tests in 13.189s`; all `OK` with no unexpected warnings.
- `python -m py_compile .\\codex_free_wrapper.py`: exit `0`.
- ASCII-safe Trust & settings app smoke: `APP_SMOKE_OK False True normal normal`; `APP_DESTROY_OK True True`.
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

The selective-apply lifecycle closeout, progressive-disclosure shell, compact workflow rail, CodeRouter window icon, model/queue disclosure, evidence-first Activity presentation, review-inspector refinement, and Trust & settings disclosure are complete and verified. Trust & settings keeps Apply Policy and safety actions visible, is collapsed by default, auto-opens only for current inspect/verification permission requests, and remains a bounded redacted UI-only view. Partial Apply -> Undo returns to REVIEW only for a non-empty same-run accepted pending proposal; full Apply Undo remains IDLE; remaining Apply stays transactional. All surfaces preserve existing worker, overseer, permission, and lifecycle boundaries.

## Next bounded roadmap

Proceed only with an explicitly assigned bounded slice, one at a time:

1. Review and freeze the current Workbench safety surfaces before the next explicitly assigned roadmap item.

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
