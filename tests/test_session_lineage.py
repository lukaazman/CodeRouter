import json
import os
import tempfile
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


def make_snapshot(root, task_id="task-lineage", session_id="session-lineage", parent_task_id="", parent_session_id=""):
    return wrapper.create_run_snapshot(
        project_root=root,
        extra_context_paths=(),
        session_messages=(),
        apply_mode=wrapper.APPLY_MODE_REVIEW,
        run_id=f"run-{task_id}",
        task_id=task_id,
        request_text="Inspect the bounded session metadata.",
        session_id=session_id,
        parent_task_id=parent_task_id,
        parent_session_id=parent_session_id,
    )


class SessionLineageStoreTests(unittest.TestCase):
    def test_restart_roundtrip_preserves_stable_session_and_parent_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "history.json"
            snapshot = make_snapshot(root, task_id="task-1", session_id="session-1")
            record = wrapper.HistoryRecord.start(snapshot, detail="Preparing plan")
            store = wrapper.HistoryStore(path)
            self.assertTrue(store.append(record))

            reloaded = wrapper.HistoryStore(path).load()
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(reloaded[0].session_id, "session-1")
            self.assertEqual(reloaded[0].parent_task_id, "")
            self.assertEqual(reloaded[0].parent_session_id, "")
            self.assertEqual(wrapper.HistoryStore(path).load()[0].session_id, reloaded[0].session_id)

    def test_parent_continuation_keeps_session_and_links_parent_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parent = make_snapshot(root, task_id="parent-task", session_id="session-1")
            child = make_snapshot(
                root,
                task_id="child-task",
                session_id=parent.session_id,
                parent_task_id=parent.task_id,
                parent_session_id=parent.session_id,
            )
            child_record = wrapper.HistoryRecord.start(child)
            self.assertEqual(child.session_id, parent.session_id)
            self.assertEqual(child_record.session_id, parent.session_id)
            self.assertEqual(child_record.parent_task_id, parent.task_id)
            self.assertEqual(child_record.parent_session_id, parent.session_id)

    def test_transition_and_identifier_bounds_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = make_snapshot(root, task_id="bounded-task", session_id="bounded-session")
            record = replace(
                wrapper.HistoryRecord.start(snapshot),
                state_transitions=tuple(
                    ("review", f"detail-{index}", f"timestamp-{index}")
                    for index in range(wrapper.HISTORY_MAX_TRANSITIONS * 2)
                ),
                session_id="s" * (wrapper.SESSION_ID_MAX_CHARS + 20),
                parent_task_id="",
                parent_session_id="",
            ).sanitized()
            self.assertLessEqual(len(record.state_transitions), wrapper.HISTORY_MAX_TRANSITIONS)
            self.assertLessEqual(len(record.session_id), wrapper.SESSION_ID_MAX_CHARS)
            self.assertEqual(len(record.state_transitions), wrapper.HISTORY_MAX_TRANSITIONS)
            self.assertEqual(record.state_transitions[0][1], "detail-80")

    def test_corrupt_oversized_and_secret_lineage_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "history.json"
            store = wrapper.HistoryStore(path, max_bytes=2048)
            secret_record = {
                "task_id": "secret-task",
                "session_id": "Bearer raw-session-token",
                "parent_task_id": "",
                "parent_session_id": "",
                "project_root": str(root),
                "request_summary": "safe",
            }
            path.write_text(json.dumps({"version": 1, "records": [secret_record]}), encoding="utf-8")
            self.assertEqual(store.load(), [])

            oversized = {
                "task_id": "oversized-task",
                "session_id": "s" * (wrapper.SESSION_ID_MAX_CHARS + 1),
                "project_root": str(root),
            }
            path.write_text(json.dumps({"version": 1, "records": [oversized]}), encoding="utf-8")
            self.assertEqual(store.load(), [])

            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(store.load(), [])

    def test_lineage_persistence_contains_no_material_or_undo_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "history.json"
            snapshot = make_snapshot(root, task_id="material-free", session_id="session-safe")
            record = replace(
                wrapper.HistoryRecord.start(snapshot),
                request_summary="safe request",
                reasons=("selected free model",),
            )
            self.assertTrue(wrapper.HistoryStore(path).append(record))
            disk = path.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_FILE_CONTENT", disk)
            self.assertNotIn("diff --git", disk)
            self.assertNotIn("STREAM_RESPONSE_SECRET", disk)
            self.assertNotIn("original_bytes", disk)
            self.assertNotIn("undo", disk.casefold())


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class SessionLineageUiTests(unittest.TestCase):
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
        self.history_path = Path(self.temp_dir.name) / "history.json"
        self.app = wrapper.CodeAgentApp(history_path=self.history_path)
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_resume_roundtrip_sets_fresh_plan_gate_without_side_effects(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            snapshot = make_snapshot(root, task_id="resume-task", session_id="resume-session")
            plan = wrapper.ExecutionPlan(
                "Safe plan metadata",
                (wrapper.PlanStep("1", "Inspect", "Read bounded metadata only"),),
            )
            record = replace(wrapper.HistoryRecord.start(snapshot), plan_summary=plan.summary, plan_steps=plan.steps).sanitized()
            self.assertTrue(self.app.history_store.append(record))
            self.app._last_apply_undo = object()
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.assertTrue(self.app.resume_task(record.task_id))

            thread_class.assert_not_called()
            self.assertEqual(self.app.session_id, record.session_id)
            self.assertTrue(self.app.resume_requires_fresh_plan)
            self.assertIsNone(self.app.lifecycle.active_run_id)
            self.assertIsNone(self.app.pending_plan)
            self.assertIsNone(self.app.approved_plan)
            self.assertIsNone(self.app.pending_proposal)
            self.assertIsNone(self.app._last_apply_undo)
            self.assertIn("Inspect", self.app.plan_preview.get("1.0", tk.END))
            self.assertEqual(self.app.instructions.get("1.0", tk.END).strip(), record.request_summary)

    def test_root_mismatch_is_inspection_only_and_does_not_switch_current_root(self):
        with tempfile.TemporaryDirectory() as current_dir, tempfile.TemporaryDirectory() as recorded_dir:
            current_root = Path(current_dir)
            recorded_root = Path(recorded_dir)
            record = wrapper.HistoryRecord.start(make_snapshot(recorded_root, task_id="mismatch", session_id="session-mismatch"))
            self.assertTrue(self.app.history_store.append(record))
            self.app.selected_folder.set(str(current_root))
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.assertTrue(self.app.resume_task(record.task_id))

            thread_class.assert_not_called()
            self.assertEqual(Path(self.app.selected_folder.get()).resolve(), current_root.resolve())
            self.assertTrue(self.app.resume_requires_fresh_plan)
            self.assertIn("differs", self.app.summary.get("1.0", tk.END).lower())
            self.assertIsNone(self.app.lifecycle.active_run_id)

    def test_resuming_another_lineage_detaches_stale_history_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_snapshot = make_snapshot(root, task_id="first-task", session_id="session-first")
            first_record = wrapper.HistoryRecord.start(first_snapshot)
            second_snapshot = make_snapshot(
                root,
                task_id="second-task",
                session_id="session-first",
                parent_task_id=first_record.task_id,
                parent_session_id=first_record.session_id,
            )
            second_record = wrapper.HistoryRecord.start(second_snapshot)
            self.assertTrue(self.app.history_store.append(first_record))
            self.assertTrue(self.app.history_store.append(second_record))
            self.app._history_begin(first_snapshot)
            self.app._history_update(state=wrapper.TASK_STATE_APPLIED, detail="first complete", outcome=wrapper.TASK_STATE_APPLIED)
            before = self.app.history_store.get(first_record.task_id)

            self.assertTrue(self.app.resume_task(second_record.task_id))
            self.assertIsNone(self.app._history_current)
            self.app.on_close()
            after = self.app.history_store.get(first_record.task_id)
            self.assertEqual(after.outcome, before.outcome)
            self.assertEqual(after.updated_at, before.updated_at)
            self.assertEqual(self.app.history_store.get(second_record.task_id).session_id, "session-first")

    def test_resume_never_restores_worker_provider_verification_or_overseer_state(self):
        with tempfile.TemporaryDirectory() as project_dir:
            root = Path(project_dir)
            record = wrapper.HistoryRecord.start(make_snapshot(root, task_id="inspection-only", session_id="session-inspection"))
            self.assertTrue(self.app.history_store.append(record))
            self.app.verification_run_id = None
            self.app.overseer_run_id = None
            with (
                mock.patch.object(wrapper.threading, "Thread") as thread_class,
                mock.patch.object(self.app, "_start_run_worker") as start_worker,
            ):
                self.assertTrue(self.app.resume_task(record.task_id))
            thread_class.assert_not_called()
            start_worker.assert_not_called()
            self.assertFalse(self.app.run_resources.worker_handles)
            self.assertFalse(self.app.run_resources.provider_response_handles)
            self.assertFalse(self.app.run_resources.process_handles)
            self.assertTrue(self.app.resume_requires_fresh_plan)
            self.assertIsNone(self.app.pending_proposal)
            self.assertIsNone(self.app.approved_plan)


if __name__ == "__main__":
    unittest.main()
