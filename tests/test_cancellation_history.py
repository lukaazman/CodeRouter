import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import codex_free_wrapper as wrapper
from tests.ui_test_helpers import build_hidden_app


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class CancellationHistoryTests(unittest.TestCase):
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

    def activate(self, run_id, state):
        root = Path(self.temp_dir.name)
        snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="Cancel one bounded action.",
        )
        self.app._history_begin(snapshot, initial_state=state, detail="active")
        self.app._activate_run(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(state, "active")
        return snapshot

    def record_for(self, snapshot):
        record = self.app.history_store.get(snapshot.task_id or snapshot.run_id)
        self.assertIsNotNone(record)
        return record

    def test_plan_cancel_persists_cancelled_history_outcome(self):
        snapshot = self.activate("cancel-plan-history", wrapper.TASK_STATE_PLAN)
        plan = wrapper.ExecutionPlan(
            "Cancel this plan.",
            (wrapper.PlanStep("1", "Inspect", "Inspect the bounded project scope."),),
        )
        self.app._set_pending_plan(plan, snapshot.run_id)

        self.app.cancel_plan()

        record = self.record_for(snapshot)
        self.assertEqual(record.outcome, "cancelled")
        self.assertIn("plan cancelled by user", record.reasons)
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)

    def test_inspect_cancel_persists_cancelled_history_outcome(self):
        snapshot = self.activate("cancel-inspect-history", wrapper.TASK_STATE_RUNNING)
        self.app.inspect_request = wrapper.InspectRequest(
            summary="Read bounded context",
            paths=("README.md",),
            run_id=snapshot.run_id,
            round=0,
        )

        self.assertTrue(self.app.cancel_inspect())

        record = self.record_for(snapshot)
        self.assertEqual(record.outcome, "cancelled")
        self.assertIn("inspect cancelled by user", record.reasons)
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REJECTED)

    def test_verification_cancel_is_cancelled_but_deny_remains_rejected(self):
        cancelled = self.activate("cancel-verification-history", wrapper.TASK_STATE_RUNNING)
        self.app.verification_request = wrapper.VerificationRequest(
            command="python -m py_compile sample.py",
            run_id=cancelled.run_id,
        )

        self.assertTrue(self.app.cancel_verification_request())

        cancelled_record = self.record_for(cancelled)
        self.assertEqual(cancelled_record.outcome, "cancelled")
        self.assertIn("verification cancelled by user", cancelled_record.reasons)
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REJECTED)

        denied = self.activate("deny-verification-history", wrapper.TASK_STATE_RUNNING)
        self.app.verification_request = wrapper.VerificationRequest(
            command="python -m py_compile sample.py",
            run_id=denied.run_id,
        )

        self.assertTrue(self.app.deny_verification())

        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REJECTED)
        self.assertEqual(self.app.status.get(), "REJECTED · Verification denied")


if __name__ == "__main__":
    unittest.main()
