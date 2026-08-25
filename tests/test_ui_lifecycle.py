import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper
from tests.ui_test_helpers import build_hidden_app


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class UiLifecycleTests(unittest.TestCase):
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
        self.app = build_hidden_app(wrapper)

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def snapshot(self, root, run_id, apply_mode=wrapper.APPLY_MODE_REVIEW):
        return wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=apply_mode,
            run_id=run_id,
        )

    def activate(self, root, run_id="run-1", apply_mode=wrapper.APPLY_MODE_REVIEW, state=wrapper.TASK_STATE_REVIEW):
        snapshot = self.snapshot(root, run_id, apply_mode)
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(state, "test")
        return snapshot

    def set_pending(self, snapshot, root, content="after"):
        target = Path(root) / "note.txt"
        target.write_text("before", encoding="utf-8")
        proposal = wrapper.create_pending_proposal(
            snapshot,
            [{"path": "note.txt", "content": content}],
        )
        self.app._set_pending_proposal(proposal)
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
        return proposal

    def test_active_run_locks_controls_and_gates_post_invalidation_events(self):
        with tempfile.TemporaryDirectory() as project:
            snapshot = self.activate(Path(project), state=wrapper.TASK_STATE_COLLECTING)
            for button in (
                self.app.run_button,
                self.app.scan_button,
                self.app.project_button,
                self.app.context_add_button,
                self.app.context_clear_button,
                self.app.new_chat_button,
                self.app.review_mode_button,
                self.app.auto_mode_button,
            ):
                self.assertEqual(str(button.cget("state")), tk.DISABLED)

            self.assertFalse(self.app.scan_folder(silent=True))
            self.assertIn("scan blocked", self.app.activity.get("1.0", tk.END).lower())

            self.app.lifecycle.invalidate()
            self.app.set_task_state(wrapper.TASK_STATE_IDLE, "Invalidated")
            self.assertEqual(str(self.app.scan_button.cget("state")), tk.NORMAL)
            emitted = wrapper.queue_run_event(
                self.app.work_queue,
                snapshot.run_id,
                "summary",
                "must not queue",
                is_current=lambda: self.app._run_is_current(snapshot.run_id),
            )
            self.assertFalse(emitted)
            self.assertTrue(self.app.work_queue.empty())

    def test_reset_folder_and_close_filter_stale_updates(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_root = Path(first_dir)
            second_root = Path(second_dir)

            reset_snapshot = self.activate(first_root, run_id="reset-run", state=wrapper.TASK_STATE_RUNNING)
            wrapper.queue_run_event(self.app.work_queue, reset_snapshot.run_id, "summary", "late reset")
            self.app.reset_session()
            self.app._poll_queue()
            self.assertNotIn("late reset", self.app.summary.get("1.0", tk.END))
            self.assertFalse(self.app.lifecycle.accepts(reset_snapshot.run_id))

            folder_snapshot = self.activate(first_root, run_id="folder-run")
            wrapper.queue_run_event(self.app.work_queue, folder_snapshot.run_id, "summary", "late folder")
            with mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(second_root)):
                self.app.choose_folder()
            self.app._poll_queue()
            self.assertEqual(Path(self.app.selected_folder.get()).resolve(), second_root.resolve())
            self.assertNotIn("late folder", self.app.summary.get("1.0", tk.END))
            self.assertFalse(self.app.lifecycle.accepts(folder_snapshot.run_id))

            close_snapshot = self.activate(second_root, run_id="close-run", state=wrapper.TASK_STATE_RUNNING)
            late_event = (close_snapshot.run_id, "summary", "late close")
            self.app.on_close()
            self.assertTrue(self.app.lifecycle.closed)
            self.assertFalse(wrapper.event_matches_run(late_event, close_snapshot.run_id, self.app.lifecycle.closed))

    def test_pending_proposal_has_discard_and_reject_semantics(self):
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            snapshot = self.activate(root, run_id="discard-run")
            self.set_pending(snapshot, root)
            self.app.reset_session()
            self.assertIsNone(self.app.pending_proposal)
            self.assertIn("discard:", self.app.activity.get("1.0", tk.END).lower())
            self.assertTrue(any("discarded" in item["content"] for item in self.app.session_messages))

            second_snapshot = self.activate(root, run_id="reject-run")
            self.set_pending(second_snapshot, root, content="rejected")
            self.app.reject_pending()
            self.assertIsNone(self.app.pending_proposal)
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REJECTED)
            self.assertIn("rejected", self.app.activity.get("1.0", tk.END).lower())
            self.assertTrue(any("rejected" in item["content"] for item in self.app.session_messages))

    def test_apply_mode_cannot_diverge_from_auto_snapshot(self):
        with tempfile.TemporaryDirectory() as project:
            snapshot = self.activate(
                Path(project),
                run_id="auto-run",
                apply_mode=wrapper.APPLY_MODE_AUTO,
                state=wrapper.TASK_STATE_RUNNING,
            )
            self.assertEqual(snapshot.apply_mode, wrapper.APPLY_MODE_AUTO)
            self.assertEqual(self.app.apply_mode.get(), wrapper.APPLY_MODE_AUTO)
            self.app.apply_mode.set(wrapper.APPLY_MODE_REVIEW)
            self.app._on_apply_mode_changed()
            self.assertEqual(self.app.apply_mode.get(), wrapper.APPLY_MODE_AUTO)
            self.assertTrue(self.app.auto_apply.get())
            self.assertEqual(str(self.app.auto_mode_button.cget("state")), tk.DISABLED)
            self.assertIn("apply mode change blocked", self.app.activity.get("1.0", tk.END).lower())

    def test_applied_state_survives_post_apply_scan(self):
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            self.app.selected_folder.set(str(root))
            snapshot = self.activate(root, run_id="apply-run")
            self.set_pending(snapshot, root, content="after apply")
            self.app.apply_pending()
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "after apply")
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
            self.assertIn("APPLIED", self.app.status.get())
            self.assertIsNone(self.app.pending_proposal)

    def test_queue_event_flow_reaches_apply_pending(self):
        with tempfile.TemporaryDirectory() as project:
            root = Path(project)
            self.app.selected_folder.set(str(root))
            snapshot = self.activate(
                root,
                run_id="queue-auto-run",
                apply_mode=wrapper.APPLY_MODE_AUTO,
                state=wrapper.TASK_STATE_RUNNING,
            )
            proposal = self.set_pending(snapshot, root, content="queue applied")
            self.app._clear_pending_proposal()
            self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "Provider complete")
            wrapper.queue_run_event(self.app.work_queue, snapshot.run_id, "proposal", proposal)
            wrapper.queue_run_event(
                self.app.work_queue,
                snapshot.run_id,
                "task_state",
                (wrapper.TASK_STATE_REVIEW, "Review pending"),
            )
            wrapper.queue_run_event(self.app.work_queue, snapshot.run_id, "auto_apply")
            self.app._poll_queue()
            self.assertEqual((root / "note.txt").read_text(encoding="utf-8"), "queue applied")
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
            self.assertIsNone(self.app.pending_proposal)

    def test_direct_destroy_clears_poll_timer_before_next_tk_instance(self):
        first_app = self.app
        self.assertIsNotNone(first_app._poll_after_id)
        first_app.destroy()
        self.assertIsNone(first_app._poll_after_id)
        self.app = None

        second_app = wrapper.CodeAgentApp()
        second_app.withdraw()
        try:
            self.assertIsNotNone(second_app._poll_after_id)
        finally:
            second_app.destroy()
            self.assertIsNone(second_app._poll_after_id)

if __name__ == "__main__":
    unittest.main()
