# CodeRouter Continuation Plan

Checkpoint: 2026-08-25 — P0 resource-scope regression closed

The P0 resource-scope gate is green and overseer-approved. The repository is intentionally left uncommitted and unpushed. Do not start a new feature until the next bounded slice is explicitly approved.

## Current checkpoint

The current slice is selective review/apply:

- the review tree supports multi-selection;
- `Apply selected` applies only the selected validated edits;
- the operation remains transactional and preserves the unselected edits as pending review work;
- Undo rolls back only the last successful selected transaction;
- the existing full `Apply` path remains available and review-gated.

The broader implementation already includes the dark Workbench shell, free-model discovery and fallback queue, capability-aware model selection, streaming timeline, project instructions, plan approval, safe inspect/verify loops, executor-to-overseer evidence handoff, continuation gates, permission ledger, task export, session lineage, command palette, and bounded Undo.

## Verification state at pause

- Post-lifecycle `python -m py_compile .\\codex_free_wrapper.py`: passed.
- Post-lifecycle full suite: green in three consecutive runs, each 216 tests OK with no unexpected warnings.
- Focused selective/apply/undo/proposal/history tests: passed after lifecycle closeout.
- Former task-history regression `test_plan_review_apply_reject_error_reset_and_close_are_recorded`: passed (`Ran 1 test ... OK`).
- Tk smoke: passed.
- Application init/update/destroy smoke: passed with `APP_SMOKE_OK idle False False False extended disabled disabled` and `APP_DESTROY_OK`.
- Direct Tk marker: `TK_SMOKE_OK`.
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

The selective-apply lifecycle closeout is complete and overseer-approved: partial Apply -> Undo returns to REVIEW only for a non-empty same-run accepted pending proposal; full Apply Undo remains IDLE; remaining Apply stays transactional. Verification-only closeout is complete. Freeze selective Apply/Undo and do not open another implementation slice until a new bounded task is explicitly assigned.

## Worker / executor instructions

On continuation, the worker must:

1. Read this file and inspect the current uncommitted diff before editing.
2. Locate the existing lifecycle/resource lineage helpers, proposal guards, selected-apply path, and Undo path. Reuse those helpers rather than inventing a second run-id system.
3. Make only the bounded P0 scope fix and its regression test. Do not add a new feature, redesign unrelated UI, commit, or push.
4. Run the focused failing history test first, then the selective/apply/undo/proposal tests.
5. Run the full suite three consecutive times. Every run must pass with no unexpected warnings.
6. Run compile, Tk smoke, application init/update/destroy smoke, and `git diff --check`.
7. Return a concise handoff containing changed files, exact commands and results, remaining risks, and the single next action. A green compile alone is not sufficient evidence.

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

The overseer resumes as a reviewer of this exact checkpoint, not as a feature planner. It must:

1. Review the worker diff before accepting it.
2. Confirm the P0 regression is fixed without weakening review-first behavior, explicit permission decisions, stale-event filtering, rollback, or process cleanup.
3. Confirm selective Apply keeps unselected edits pending, failed writes roll back, rejected confirmation performs no write, and selected-only Undo remains bounded.
4. Confirm the new stale-handle regression and the existing task-history regression both pass.
5. Require the three consecutive full-suite passes plus compile, Tk/app smoke, and diff-check before approval.
6. Return `approved` only when all gates are green. Otherwise return `needs_attention` with one concrete bounded correction for the worker.

After approval, the only permitted next slice is a small selective-apply lifecycle closeout/review. The overseer must not open another feature queue until the P0 gate is green and the worker has supplied evidence.

## Continuation protocol

Every worker cycle follows this order:

`read handoff -> inspect diff -> one bounded change -> focused tests -> full gates -> overseer review -> next bounded slice`

The user can continue by sending the next instruction to the main task; the main task routes implementation work to the worker and evidence/review work to the overseer. Until the P0 gate passes, the correct next instruction is only to finish and verify the resource-scope regression.

## Known boundaries

- No live provider/OpenRouter runtime claim is required for this checkpoint; mocked/local verification is sufficient.
- No commit or push has been performed.
- The current working tree contains uncommitted CodeRouter changes; preserve them and do not reset or discard unrelated work.
- Do not include raw project files, raw diffs, or stream bodies in task history, handoffs, exports, or permission metadata.
