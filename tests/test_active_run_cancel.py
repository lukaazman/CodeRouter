import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper
from tests.ui_test_helpers import build_hidden_app


class ClosableResponse:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ActiveRunCancellationTests(unittest.TestCase):
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

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def activate(self, run_id="cancel-run", state=wrapper.TASK_STATE_RUNNING):
        root = Path(self.temp_dir.name)
        snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="Cancel this bounded active run.",
        )
        self.app._history_begin(snapshot, initial_state=state, detail="active")
        self.app._activate_run(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app.set_task_state(state, "active")
        return snapshot

    def test_stop_control_is_disabled_idle_and_enabled_for_active_run(self):
        self.assertEqual(str(self.app.stop_button.cget("state")), tk.DISABLED)

        self.activate(state=wrapper.TASK_STATE_COLLECTING)
        self.assertEqual(str(self.app.stop_button.cget("state")), tk.NORMAL)

    def test_active_cancel_finishes_history_invalidates_resources_and_filters_late_events(self):
        snapshot = self.activate()
        response = ClosableResponse()
        self.assertTrue(self.app.run_resources.register_response(snapshot.run_id, response))

        self.assertTrue(self.app.cancel_active_run())
        self.assertTrue(response.closed)
        self.assertIsNone(self.app.lifecycle.active_run_id)
        self.assertIsNone(self.app._history_current)
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)
        self.assertEqual(self.app.status.get(), "IDLE · Cancelled")
        self.assertEqual(str(self.app.stop_button.cget("state")), tk.DISABLED)

        record = self.app.history_store.get(snapshot.task_id or snapshot.run_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.outcome, "cancelled")
        self.assertIn("active run cancelled by user", record.reasons)

        self.app.work_queue.put(
            wrapper.RunEvent(snapshot.run_id, "summary", "late stale summary", 999)
        )
        self.app._poll_queue()
        self.assertNotIn("late stale summary", self.app.summary.get("1.0", tk.END))

    def test_stop_routes_pending_actions_to_existing_cancel_methods(self):
        snapshot = self.activate(state=wrapper.TASK_STATE_PLAN)
        self.app.pending_plan = object()
        with mock.patch.object(self.app, "cancel_plan", return_value=None) as cancel_plan:
            self.assertTrue(self.app.cancel_active_run())
        cancel_plan.assert_called_once_with()

        self.app.pending_plan = None
        self.app.inspect_request = wrapper.InspectRequest(
            summary="Need bounded context",
            paths=("README.md",),
            run_id=snapshot.run_id,
            round=0,
        )
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "inspect permission")
        with mock.patch.object(self.app, "cancel_inspect", return_value=True) as cancel_inspect:
            self.assertTrue(self.app.cancel_active_run())
        cancel_inspect.assert_called_once_with()

        self.app.inspect_request = None
        self.app.verification_request = wrapper.VerificationRequest(
            command="python -m py_compile sample.py",
            run_id=snapshot.run_id,
        )
        with mock.patch.object(
            self.app,
            "cancel_verification_request",
            return_value=True,
        ) as cancel_verification:
            self.assertTrue(self.app.cancel_active_run())
        cancel_verification.assert_called_once_with()

    def test_escape_uses_active_cancel_after_existing_higher_priority_actions(self):
        self.activate()
        with mock.patch.object(self.app, "cancel_active_run", return_value=True) as cancel_active:
            self.app._on_escape_shortcut(None)
        cancel_active.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
