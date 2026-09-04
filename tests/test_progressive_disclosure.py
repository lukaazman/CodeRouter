import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import CodeRouter as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ProgressiveDisclosureUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.project_dir = tempfile.TemporaryDirectory()
        self.history_dir = tempfile.TemporaryDirectory()
        self.config_dir = tempfile.TemporaryDirectory()
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
        self.project_dir.cleanup()
        self.history_dir.cleanup()
        self.config_dir.cleanup()

    def activate_snapshot(self, run_id="progressive-disclosure"):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="progressive disclosure test",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        return snapshot

    def test_secondary_groups_are_collapsed_and_primary_review_path_stays_visible(self):
        self.assertEqual(
            self.app._disclosure_expanded,
            {
                "context": False,
                "history": False,
                "verification": False,
                "activity": False,
                "task_tools": False,
            },
        )
        for section in self.app._disclosure_widgets:
            self.assertTrue(
                all(widget.grid_info() == {} for widget in self.app._disclosure_widgets[section]),
                section,
            )

        for name in (
            "project_button",
            "run_button",
            "scan_button",
            "new_chat_button",
            "instructions",
            "summary",
            "apply_button",
            "apply_selected_button",
            "reject_button",
            "edited_files",
            "diff",
        ):
            self.assertNotEqual(getattr(self.app, name).grid_info(), {}, name)

        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)

    def test_each_disclosure_toggles_round_trip_and_is_focusable(self):
        for section, button in self.app._disclosure_buttons.items():
            with self.subTest(section=section):
                self.assertIn(str(button.cget("takefocus")).casefold(), {"1", "true"})
                self.assertTrue(button.bind("<Return>"))
                self.assertTrue(button.bind("<space>"))
                button.invoke()
                self.assertTrue(self.app._disclosure_expanded[section])
                self.assertTrue(
                    any(widget.grid_info() for widget in self.app._disclosure_widgets[section])
                )
                button.invoke()
                self.assertFalse(self.app._disclosure_expanded[section])
                self.assertTrue(
                    all(widget.grid_info() == {} for widget in self.app._disclosure_widgets[section])
                )

    def test_active_request_and_running_work_auto_open_relevant_groups(self):
        snapshot = self.activate_snapshot()
        self.app.inspect_request = wrapper.InspectRequest(
            summary="Need bounded source context",
            paths=("README.md",),
            run_id=snapshot.run_id,
            round=0,
        )
        self.app._update_lifecycle_controls()

        self.assertTrue(self.app._disclosure_expanded["task_tools"])
        self.assertTrue(self.app._disclosure_expanded["activity"])
        self.assertTrue(self.app._disclosure_expanded["verification"] is False)
        self.assertNotEqual(self.app.allow_inspect_button.grid_info(), {})
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)

        self.app._toggle_disclosure("task_tools")
        self.assertTrue(self.app._disclosure_expanded["task_tools"])

        self.app.inspect_request = None
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "mock running state")
        self.assertTrue(self.app._disclosure_expanded["task_tools"])
        self.assertTrue(self.app._disclosure_expanded["activity"])

    def test_ready_overseer_handoff_auto_opens_task_tools_and_send_stays_visible(self):
        snapshot = self.activate_snapshot("ready-overseer-handoff")
        self.app._handoff_snapshot = snapshot
        self.app._handoff_created_at = "2026-01-01T00:00:00+00:00"
        self.app._handoff_stale = False
        self.app.run_timeline = []
        self.app._handoff_evidence_events = []
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review ready")
        self.app._update_lifecycle_controls()

        self.assertIsNotNone(self.app._current_report_handoff())
        self.assertTrue(self.app._disclosure_expanded["task_tools"])
        self.assertNotEqual(self.app._disclosure_widgets["task_tools"][-1].grid_info(), {})
        self.assertEqual(str(self.app.send_overseer_button.cget("state")), tk.NORMAL)

    def test_toggle_preserves_existing_inputs_and_no_execution_side_effects(self):
        prompt = "Keep this prompt while panels change."
        self.app.instructions.delete("1.0", tk.END)
        self.app.instructions.insert("1.0", prompt)
        self.app.verification_command.set("python -m py_compile sample.py")
        self.app.local_command.set("/status")
        self.app.activity.insert("1.0", "existing activity")

        for section in self.app._disclosure_buttons:
            self.app._disclosure_buttons[section].invoke()
        for section in self.app._disclosure_buttons:
            self.app._disclosure_buttons[section].invoke()

        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), prompt)
        self.assertEqual(self.app.verification_command.get(), "python -m py_compile sample.py")
        self.assertEqual(self.app.local_command.get(), "/status")
        self.assertIn("existing activity", self.app.activity.get("1.0", "end-1c"))
        self.assertIsNone(self.app.pending_proposal)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)


if __name__ == "__main__":
    unittest.main()
