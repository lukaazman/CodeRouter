# CodeRouter Continuation Plan

Checkpoint: 2026-08-25 — Combined no-window UI, icon, scanned-context, History-search, Activity, and Undo hardening verified; approval pending

This checkpoint freezes the current Workbench rework before the next roadmap slice. The P0 resource-scope gate, compact workflow rail, CodeRouter window icon, model/queue disclosure, evidence-first Activity, review inspector, Trust & settings, Command palette disclosure, read-only scanned-context map, metadata-only History search, scanned-root availability hardening, and selective Apply/Undo lifecycle are implemented in the working tree. Worker and overseer cycles review and test only; the main task alone commits and pushes.

## Safety and window boundary

CodeAgentApp.__init__() withdraws immediately after super().__init__(), before protocol, title, geometry, icon, or UI setup. Only the fully initialized production main() reveals the app. Tests use hidden CodeAgentApp fixtures or no-window tk.Tcl() probes; there are no standalone probe roots, and tests never call deiconify(), mainloop(), focus_force(), event_generate(), or a visible app launch. Do not run the app for routine checks. If a real runtime check is ever unavoidable, launch it hidden/off-screen and terminate it without activating or flashing a taskbar/window surface.

## Current checkpoint

- Compact workflow rail exposes truthful PHASE, MODEL-QUEUE, and NEXT values without inventing model identity or changing provider/model selection.
- MODEL / QUEUE expands on click, Return, or Space and shows bounded redacted model status, deterministic free fallback queue, health metadata, and active-run signal.
- Activity digest exposes bounded phase/run, timeline, permission, error/blocker, and last-evidence metadata. The existing append-only Activity log remains the source of truth.
- PreservingActivityLog keeps the existing widget, callbacks, content, and logical yview across disclosure transitions.
- Review inspector preserves Treeview identity, multi-selection, diff behavior, Apply selected, and transactional review/apply behavior while exposing compact selected/total and relative-path metadata.
- Trust & settings is collapsed by default but auto-opens for current inspect/verification permission requests. It does not hide Apply Policy or safety actions and does not add execution behavior.
- Local command disclosure keeps exact-command, redaction, read-only, stale, closed, and explicit user-action guards. Ctrl+K expands and uses focus_set() without submitting.
- Scanned context is collapsed by default and exposes only bounded redacted metadata from the latest successful Tk-thread scan. Missing/changed roots, non-directories, reset, failure, and stale previews clear old paths.
- History search is collapsed by default, case-insensitive, metadata-only, bounded, in-memory, and persistence-free. No-match selection clears safely; blank search restores the existing inspect-only browser.
- History, Manual verification, Activity, and Task tools stay collapsed by default; primary project/task controls, prompt, summary/status, review state, changed files, diff, and review actions remain visible.
- Active plan, inspect, verification, running work, permission actions, and ready/active Executor -> Overseer handoff state auto-open the relevant disclosure.
- assets/code-router.svg is bundled and byte-identical to C:\Users\Luka\Documents\GitHub\Portfolio\assets\projects\code-router.svg. The dependency-free 32x32 Tk PhotoImage honors the canonical rounded mark (rx=48), uses transparency_set outside the mark where supported, retains the image on the app, and fails closed if icon setup is unavailable. The toolbar reuses the same image; no Portfolio path is used at runtime.
- Selective review/apply remains multi-file, transactional, review-gated, and preserves unselected edits. Partial Apply -> Undo is available only for a non-empty accepted same-run pending proposal; full Apply -> Undo returns to IDLE.
- Activating a different snapshot/run clears a prior-run _last_apply_undo transaction before a new proposal can be reviewed. Same-run partial Apply -> Undo remains available.
- Existing free-agent discovery, capability-aware selection, fallback queue, streaming timeline, project instructions, plan approval, inspect/verify loops, executor-to-overseer evidence handoff, continuation gates, permission ledger, task export, session lineage, command palette, and bounded Undo remain the underlying behavior.

## Verified evidence

- Focused hidden regression checks: worker ran 19 tests in 2.030s — OK, covering Undo invalidation, hidden app construction, scanned context, History search, and UI lifecycle.
- Latest full hidden suite: python -m unittest discover -s tests -p "test_*.py" — Ran 263 tests in 15.095s — OK.
- python -m py_compile codex_free_wrapper.py — exit 0.
- Static test scan contains no tk.Tk(), deiconify, mainloop, focus_force, or event_generate calls.
- No CodeRouter/python/pythonw process was left running; no visible app, taskbar surface, or focus-stealing smoke path was used.
- Icon transparency regression passed when Tk supports transparency_get; the bundled SVG hash matches the Portfolio source byte-for-byte.
- git diff --check passed; only normal LF-to-CRLF notices were reported.

## Resource-scope invariant

Active-resource checks are run-scoped: include the current proposal/lifecycle run and linked verification/overseer child runs; ignore unrelated stale run IDs; block genuinely active current workers, provider responses, and processes; apply the same scope to normal Apply, Apply selected, and Undo; preserve stale-event filtering and cleanup; never weaken lifecycle safety or clear registries globally. Keep the regression proving stale handles do not block the current Apply while current-run handles still do.

## Next bounded roadmap

Proceed one bounded slice at a time:

1. Review and freeze the current Workbench disclosure surfaces, including scanned context, History search, Activity scroll preservation, hidden startup, exact Portfolio icon usage, and prior-run Undo invalidation.
2. Improve the next highest-value Codex/Claude-Code-style workflow gap only after slice 1 is approved: prefer visible progress/evidence, queue transparency, cancellation/recovery, or safe task-history continuity.
3. Continue performance and safety hardening without adding paid-provider dependence, heavy AI visual effects, gradients, oversized rounded cards, hidden permission changes, or unrelated capability.

Every slice must preserve the primary workflow and remain limited to its focused regression tests. Do not add a provider, command, persistence, or permission capability unless explicitly assigned by the main task.

## Worker / executor instructions

1. Read this plan and inspect the current uncommitted diff before editing.
2. Take exactly one approved roadmap item and keep the patch limited to that slice and focused tests.
3. Reuse existing UI, lifecycle, lineage, resource, permission, history, proposal, Apply/Undo, worker, and Overseer helpers. Do not invent a second run-id system or weaken a guard.
4. Preserve review-first behavior, plan/inspect/verification gates, root/path safety, cancellation, stale-event filtering, redaction, transactional rollback, no-Tk-from-worker behavior, and hidden/no-flash startup.
5. Run focused tests, the full hidden suite, compile, hidden UI lifecycle checks, and git diff --check. Report exact results and any provider/OS limitation. Never run main(), deiconify(), mainloop(), focus_force(), event_generate(), or a visible Tk probe.
6. Return changed files, evidence, remaining risks, and one next bounded action.
7. Do not commit or push. Only the main task may publish after Overseer approval.

## Overseer instructions

1. Review the worker diff before accepting it.
2. Confirm the slice changes only its approved surface and preserves review-first behavior, explicit permission decisions, stale-event filtering, cancellation, rollback, resource cleanup, and worker/Overseer isolation.
3. Confirm exact focused-test, full-suite, compile, hidden UI, and diff-check evidence.
4. Return approved only when the gates are green. Otherwise return needs_attention with one concrete bounded correction.
5. Do not expand the roadmap, add a new capability, authorize unrelated work, commit, or push.

## Continuation protocol

Every cycle follows:

read handoff -> inspect diff -> one bounded slice -> focused hidden tests -> full hidden gates -> Overseer review -> next bounded slice

The main task routes implementation to the worker and evidence/review to the Overseer. After approval, the next cycle starts with the next roadmap item and does not reopen completed slices.

## Known boundaries

- No live provider/OpenRouter runtime claim is required for this checkpoint; mocked/local verification is sufficient.
- Compilation is not runtime proof; hidden lifecycle and regression tests are the required evidence for this checkpoint.
- Publication is controlled by the main task after approval. Preserve unrelated changes and never reset or discard them.
- Do not include raw project files, raw diffs, or stream bodies in task history, handoffs, exports, or permission metadata.
