import json
import os
import tempfile
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


def make_snapshot(root, task_id="task-1", run_id=None, request_text="Make the bounded change."):
    return wrapper.create_run_snapshot(
        project_root=root,
        extra_context_paths=(),
        session_messages=(),
        apply_mode=wrapper.APPLY_MODE_REVIEW,
        run_id=run_id or f"run-{task_id}",
        task_id=task_id,
        request_text=request_text,
    )


def make_record(root, task_id="task-1", outcome=wrapper.TASK_STATE_REVIEW):
    snapshot = make_snapshot(root, task_id=task_id)
    now = "2026-08-24T12:00:00+00:00"
    return wrapper.HistoryRecord(
        task_id=task_id,
        project_root=str(root),
        request_summary="Make the bounded change.",
        plan_summary="Review the safe change.",
        plan_steps=(
            wrapper.PlanStep("1", "Inspect", "Check the existing guard."),
        ),
        selected_model="coder/example:free",
        state_transitions=(
            (wrapper.TASK_STATE_PLAN, "Plan ready", now),
            (wrapper.TASK_STATE_REVIEW, "Review pending", now),
        ),
        reasons=("explicitly free model",),
        outcome=outcome,
        created_at=now,
        updated_at=now,
    )


class HistoryStoreTests(unittest.TestCase):
    def test_redacted_round_trip_persists_only_metadata(self):
        raw_key = "history-api-key-123456"
        raw_bearer = "history-bearer-123456"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            store = wrapper.HistoryStore(path)
            record = make_record(Path(temp_dir))
            record = replace(
                record,
                request_summary=f"api_key={raw_key}",
                reasons=(f"Authorization: Bearer {raw_bearer}",),
            )
            self.assertTrue(store.append(record))

            raw_disk = path.read_text(encoding="utf-8")
            self.assertNotIn(raw_key, raw_disk)
            self.assertNotIn(raw_bearer, raw_disk)
            loaded = store.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].selected_model, "coder/example:free")
            self.assertEqual(loaded[0].plan.steps[0].title, "Inspect")
            self.assertEqual(loaded[0].outcome, wrapper.TASK_STATE_REVIEW)

    def test_atomic_write_failure_preserves_previous_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            store = wrapper.HistoryStore(path)
            self.assertTrue(store.append(make_record(Path(temp_dir), "first")))
            original = path.read_bytes()

            with mock.patch.object(wrapper.os, "replace", side_effect=OSError("replace blocked")):
                self.assertFalse(store.append(make_record(Path(temp_dir), "second")))

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual([item.task_id for item in store.load()], ["first"])
            self.assertEqual(list(Path(temp_dir).glob(".history.json.*.tmp")), [])

    def test_corrupt_unreadable_and_oversized_history_fail_closed_and_recover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            store = wrapper.HistoryStore(path, max_bytes=4096)
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(store.load(), [])
            self.assertTrue(store.append(make_record(Path(temp_dir))))
            self.assertEqual(len(store.load()), 1)

            path.write_bytes(b"x" * 4097)
            self.assertEqual(store.load(), [])

            unreadable = Path(temp_dir) / "unreadable.json"
            unreadable.write_text("{}", encoding="utf-8")
            unreadable_store = wrapper.HistoryStore(unreadable)
            with mock.patch.object(Path, "read_text", side_effect=OSError("read blocked")):
                self.assertEqual(unreadable_store.load(), [])

    def test_history_count_and_size_bounds_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "bounded.json"
            store = wrapper.HistoryStore(path, max_records=2, max_bytes=4096)
            for index in range(4):
                self.assertTrue(store.append(make_record(root, f"task-{index}")))
            self.assertEqual([item.task_id for item in store.load()], ["task-2", "task-3"])

            bounded = wrapper.HistoryStore(root / "small.json", max_records=5, max_bytes=4096)
            large = make_record(root, "large")
            large = replace(
                large,
                request_summary="request " * 1000,
                plan_summary="plan " * 1000,
                reasons=("reason " * 1000,),
            )
            self.assertTrue(bounded.append(large))
            self.assertLessEqual(bounded.path.stat().st_size, 4096)
            self.assertLessEqual(len(bounded.load()), 5)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class TaskHistoryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.temp_dir.name) / "local_config.json"
        self.history_path = Path(self.temp_dir.name) / "app-history.json"
        self.app = wrapper.CodeAgentApp(history_path=self.history_path)
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def activate_history(self, root, task_id):
        snapshot = make_snapshot(root, task_id=task_id)
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._history_begin(snapshot)
        return snapshot

    def test_runtime_events_never_persist_files_diffs_or_stream_text(self):
        raw_key = "ui-history-api-key-123456"
        raw_bearer = "ui-history-bearer-123456"
        self.app.api_key = raw_key
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            snapshot = self.activate_history(
                root,
                "metadata-only",
            )
            self.app._history_update(
                reason=f"Authorization: Bearer {raw_bearer}",
                model="coder/example:free",
            )
            self.app._history_event(snapshot.run_id, "stream_delta", "STREAM_RESPONSE_SECRET")
            self.app._history_event(snapshot.run_id, "diffs", "+++ PRIVATE_DIFF_CONTENT")
            self.app._history_event(snapshot.run_id, "files", [{"path": "x", "content": "PRIVATE_FILE_CONTENT"}])

            disk = self.history_path.read_text(encoding="utf-8")
            self.assertNotIn(raw_key, disk)
            self.assertNotIn(raw_bearer, disk)
            self.assertNotIn("STREAM_RESPONSE_SECRET", disk)
            self.assertNotIn("PRIVATE_DIFF_CONTENT", disk)
            self.assertNotIn("PRIVATE_FILE_CONTENT", disk)
            self.assertIn("selected_model", disk)

    def test_resume_existing_root_is_inspection_only_and_needs_fresh_plan(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            record = make_record(root, "resume-existing")
            self.assertTrue(self.app.history_store.append(record))
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.assertTrue(self.app.resume_task(record.task_id))

            thread_class.assert_not_called()
            self.assertEqual(Path(self.app.selected_folder.get()).resolve(), root.resolve())
            self.assertEqual(self.app.instructions.get("1.0", tk.END).strip(), record.request_summary)
            self.assertIn(record.plan_steps[0].title, self.app.plan_preview.get("1.0", tk.END))
            self.assertTrue(self.app.resume_requires_fresh_plan)
            self.assertIsNone(self.app.lifecycle.active_run_id)
            self.assertIsNone(self.app.pending_plan)
            self.assertIsNone(self.app.approved_plan)
            self.assertIsNone(self.app.pending_proposal)
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)

    def test_history_browser_is_newest_first_and_selection_is_inspection_only(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            older = make_record(root, "older")
            newer = replace(make_record(root, "newer"), updated_at="2026-08-24T13:00:00+00:00")
            self.assertTrue(self.app.history_store.append(older))
            self.assertTrue(self.app.history_store.append(newer))
            self.app._refresh_history_browser()

            self.assertEqual([record.task_id for record in self.app._history_browser_records], ["newer", "older"])
            before_prompt = self.app.instructions.get("1.0", tk.END)
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.app.history_list.selection_set(0)
                selected = self.app._on_history_selected()

            thread_class.assert_not_called()
            self.assertEqual(selected.task_id, "newer")
            self.assertIsNone(self.app.lifecycle.active_run_id)
            self.assertEqual(self.app.instructions.get("1.0", tk.END), before_prompt)
            detail = self.app.history_detail.get("1.0", tk.END)
            self.assertIn("Task id: newer", detail)
            self.assertIn("Root status: available", detail)
            self.assertIn("Plan steps:", detail)

    def test_resuming_another_record_does_not_close_previous_history_owner(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            previous_snapshot = self.activate_history(root, "previous-owner")
            self.app._history_update(
                state=wrapper.TASK_STATE_APPLIED,
                detail="Applied before inspection resume",
                outcome=wrapper.TASK_STATE_APPLIED,
            )
            previous_before = self.app.history_store.get(previous_snapshot.task_id)
            other = make_record(root, "other-task", outcome=wrapper.TASK_STATE_REVIEW)
            self.assertTrue(self.app.history_store.append(other))

            self.assertTrue(self.app.resume_task(other.task_id))
            self.assertIsNone(self.app._history_current)
            self.app.on_close()

            previous_after = self.app.history_store.get(previous_snapshot.task_id)
            self.assertEqual(previous_after.outcome, wrapper.TASK_STATE_APPLIED)
            self.assertEqual(previous_after.updated_at, previous_before.updated_at)
            self.assertEqual(self.app.history_store.get(other.task_id).outcome, wrapper.TASK_STATE_REVIEW)

    def test_missing_or_changed_root_resume_never_restores_execution(self):
        missing_root = Path(self.temp_dir.name) / "missing-project"
        missing_record = make_record(missing_root, "resume-missing")
        self.assertTrue(self.app.history_store.append(missing_record))
        self.app.selected_folder.set(str(Path(self.temp_dir.name)))
        with mock.patch.object(wrapper.threading, "Thread") as thread_class:
            self.assertTrue(self.app.resume_task(missing_record.task_id))
        thread_class.assert_not_called()
        self.assertTrue(self.app.resume_requires_fresh_plan)
        self.assertIn("unavailable", self.app.summary.get("1.0", tk.END).lower())
        self.assertIsNone(self.app.lifecycle.active_run_id)
        self.assertIsNone(self.app.pending_proposal)

    def test_plan_review_apply_reject_error_reset_and_close_are_recorded(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            plan = wrapper.ExecutionPlan(
                "Review the bounded change.",
                (wrapper.PlanStep("1", "Inspect", "Preserve the guard."),),
            )

            plan_snapshot = self.activate_history(root, "plan-approved")
            self.app.set_task_state(wrapper.TASK_STATE_PLAN, "Approve plan")
            self.app._set_pending_plan(plan, plan_snapshot.run_id)
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.app.approve_plan()
            thread_class.assert_called_once()
            plan_record = self.app.history_store.get("plan-approved")
            self.assertIn("plan approved", " ".join(plan_record.reasons))

            apply_snapshot = self.activate_history(root, "applied")
            self.app.selected_folder.set(str(root))
            self.app._history_update(
                state=wrapper.TASK_STATE_REVIEW,
                detail="Review pending",
                outcome=wrapper.TASK_STATE_REVIEW,
            )
            target = root / "note.txt"
            target.write_text("before", encoding="utf-8")
            proposal = wrapper.create_pending_proposal(
                apply_snapshot,
                [{"path": "note.txt", "content": "after"}],
            )
            self.app._set_pending_proposal(proposal)
            self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
            self.app.apply_pending()
            self.assertEqual(self.app.history_store.get("applied").outcome, wrapper.TASK_STATE_APPLIED)

            reject_snapshot = self.activate_history(root, "rejected")
            target.write_text("before reject", encoding="utf-8")
            reject_proposal = wrapper.create_pending_proposal(
                reject_snapshot,
                [{"path": "note.txt", "content": "rejected"}],
            )
            self.app._set_pending_proposal(reject_proposal)
            self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
            self.app.reject_pending()
            self.assertEqual(self.app.history_store.get("rejected").outcome, wrapper.TASK_STATE_REJECTED)

            error_snapshot = self.activate_history(root, "errored")
            self.app._history_update(
                state=wrapper.TASK_STATE_ERROR,
                detail="provider failed",
                reason="fallback exhausted",
                outcome=wrapper.TASK_STATE_ERROR,
            )
            self.assertEqual(self.app.history_store.get("errored").outcome, wrapper.TASK_STATE_ERROR)

            reset_snapshot = self.activate_history(root, "reset")
            self.app.reset_session()
            self.assertFalse(self.app.lifecycle.accepts(reset_snapshot.run_id))
            self.assertEqual(self.app.history_store.get("reset").outcome, "reset")

            close_snapshot = self.activate_history(root, "closed")
            self.app.on_close()
            self.assertFalse(self.app.lifecycle.accepts(close_snapshot.run_id))
            self.assertEqual(self.app.history_store.get("closed").outcome, "closed")


if __name__ == "__main__":
    unittest.main()
