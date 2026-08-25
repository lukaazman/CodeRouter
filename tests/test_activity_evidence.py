import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import codex_free_wrapper as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ActivityEvidenceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.history_dir = tempfile.TemporaryDirectory()
        self.config_dir = tempfile.TemporaryDirectory()
        self.project_dir = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.config_dir.name) / "local_config.json"
        self.app = wrapper.CodeAgentApp(
            history_path=Path(self.history_dir.name) / "history.json"
        )
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.history_dir.cleanup()
        self.config_dir.cleanup()
        self.project_dir.cleanup()

    def activate_snapshot(self, run_id="activity-evidence-run"):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="activity evidence test",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        return snapshot

    def test_default_digest_is_compact_and_activity_stays_collapsed(self):
        self.assertNotEqual(self.app.activity_digest_label.grid_info(), {})
        self.assertEqual(self.app.activity.grid_info(), {})
        digest = self.app.activity_digest.get()
        self.assertIn("phase=IDLE", digest)
        self.assertIn("run=idle", digest)
        self.assertIn("events=0", digest)
        self.assertIn("permissions=0", digest)
        self.assertIn("errors/blockers=0", digest)
        self.assertIn("last=none", digest)

    def test_timeline_permission_and_error_counts_are_bounded_and_redacted(self):
        snapshot = self.activate_snapshot()
        self.app._record_timeline_event(
            snapshot.run_id,
            1,
            "model_status",
            "Selected explicitly free model",
        )
        self.app._record_timeline_event(
            snapshot.run_id,
            2,
            "status",
            "blocked: Authorization: Bearer secret-token-value",
        )
        decision = self.app._record_permission_decision(
            "inspect",
            wrapper.PERMISSION_DECISION_DENY,
            run_id=snapshot.run_id,
        )
        self.assertIsNotNone(decision)
        self.app.log("! error: Authorization: Bearer secret-token-value")

        digest = self.app.activity_digest.get()
        self.assertIn("events=3", digest)
        self.assertIn("permissions=1", digest)
        self.assertIn("errors/blockers=1", digest)
        self.assertIn("last=permission decision", digest)
        self.assertNotIn("secret-token-value", digest)
        self.assertNotIn("secret-token-value", self.app.activity.get("1.0", tk.END))

    def test_activity_round_trip_preserves_widget_content_and_scroll_state(self):
        activity = self.app.activity
        disclosure = self.app.activity_disclosure_button
        self.assertIsInstance(activity, wrapper.PreservingActivityLog)
        self.app.log("visible bounded evidence")
        before_content = activity.get("1.0", tk.END)
        before_view = activity.yview()

        disclosure.invoke()
        self.app.update_idletasks()
        self.assertNotEqual(activity.grid_info(), {})
        self.assertIs(activity, self.app.activity)
        self.assertEqual(activity.get("1.0", tk.END), before_content)

        disclosure.invoke()
        self.app.update_idletasks()
        self.assertEqual(activity.grid_info(), {})
        self.assertIs(activity, self.app.activity)
        self.assertEqual(activity.get("1.0", tk.END), before_content)
        self.assertEqual(activity.yview(), before_view)

    def test_active_run_digest_remains_truthful(self):
        snapshot = self.activate_snapshot("active-activity-evidence")
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "Collecting evidence")
        self.app._refresh_activity_digest()
        digest = self.app.activity_digest.get()
        self.assertIn("phase=RUNNING", digest)
        self.assertIn("run=active", digest)
        self.assertIn(f"events={len(self.app.run_timeline)}", digest)
        self.assertEqual(self.app.lifecycle.active_run_id, snapshot.run_id)

    def test_digest_refresh_has_no_worker_provider_or_process_side_effects(self):
        activity = self.app.activity
        self.app._refresh_activity_digest()
        self.app._refresh_workflow_rail()
        self.app._update_lifecycle_controls()
        self.assertIs(activity, self.app.activity)
        self.assertIsNone(self.app.pending_proposal)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)


if __name__ == "__main__":
    unittest.main()
