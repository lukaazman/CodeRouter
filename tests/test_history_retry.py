import os
import tempfile
import tkinter as tk
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper
from tests.ui_test_helpers import build_hidden_app


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class HistoryRetryTests(unittest.TestCase):
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
        self.app = build_hidden_app(
            wrapper,
            history_path=Path(self.temp_dir.name) / "history.json",
        )
        self.app.api_key = "history-retry-test-key"

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def saved_record(self, root, task_id="history-retry-task"):
        snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id=f"{task_id}-run",
            task_id=task_id,
            request_text="Retry this bounded task.",
        )
        record = wrapper.HistoryRecord.start(
            snapshot,
            initial_state=wrapper.TASK_STATE_ERROR,
            detail="previous attempt stopped",
        ).sanitized()
        self.assertTrue(self.app.history_store.append(record))
        self.app.selected_history_record = record
        return record

    def test_retry_button_is_compact_and_only_enabled_when_idle_and_ready(self):
        self.assertEqual(str(self.app.history_retry_button.cget("state")), tk.DISABLED)

        root = Path(self.temp_dir.name)
        self.saved_record(root)
        self.app.selected_folder.set(str(root))
        self.app._update_lifecycle_controls()
        self.assertEqual(str(self.app.history_retry_button.cget("state")), tk.NORMAL)

        active = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="history-retry-active",
        )
        self.app._activate_run(active)
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "active")
        self.assertEqual(str(self.app.history_retry_button.cget("state")), tk.DISABLED)

    def test_retry_requires_explicit_click_and_uses_fresh_resume_then_run(self):
        root = Path(self.temp_dir.name)
        record = self.saved_record(root)
        self.app.selected_folder.set(str(root))

        with (
            mock.patch.object(self.app, "resume_task", return_value=True) as resume,
            mock.patch.object(self.app, "run_agent") as run,
        ):
            self.assertTrue(self.app._history_retry_is_ready())
            self.assertTrue(self.app.retry_selected_history())

        resume.assert_called_once_with(record.task_id)
        run.assert_called_once_with()

    def test_retry_rejects_different_root_and_transient_work(self):
        root = Path(self.temp_dir.name) / "recorded"
        other_root = Path(self.temp_dir.name) / "current"
        root.mkdir()
        other_root.mkdir()
        self.saved_record(root, task_id="history-retry-root-mismatch")
        self.app.selected_folder.set(str(other_root))

        with mock.patch.object(self.app, "run_agent") as run:
            self.assertFalse(self.app.retry_selected_history())
        run.assert_not_called()

        self.app.selected_folder.set(str(root))
        pending_snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="history-retry-pending",
        )
        self.app.pending_proposal = wrapper.create_pending_proposal(
            pending_snapshot,
            [{"path": "note.txt", "content": "bounded"}],
        )
        with (
            mock.patch.object(self.app, "resume_task") as resume,
            mock.patch.object(self.app, "run_agent") as run,
        ):
            self.assertFalse(self.app.retry_selected_history())
        resume.assert_not_called()
        run.assert_not_called()

    def test_retry_rejects_empty_recorded_root_even_when_current_directory_exists(self):
        record = self.saved_record(Path(self.temp_dir.name), task_id="history-retry-empty-root")
        self.app.selected_history_record = replace(record, project_root="")
        self.app.selected_folder.set(str(Path.cwd()))

        self.assertFalse(self.app._history_retry_is_ready())
        with mock.patch.object(self.app, "run_agent") as run:
            self.assertFalse(self.app.retry_selected_history())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
