import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import codex_free_wrapper as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class WorkflowRailUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")

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

    def activate_snapshot(self, run_id="workflow-rail"):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="workflow rail test",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        return snapshot

    def test_rail_is_visible_at_startup_and_secondary_disclosures_stay_collapsed(self):
        self.assertNotEqual(self.app.workflow_rail.grid_info(), {})
        self.assertEqual(self.app.workflow_phase.get(), "IDLE")
        self.assertEqual(self.app.workflow_model_signal.get(), "Free model fallback")
        self.assertEqual(self.app.workflow_next_action.get(), "Choose a project folder")
        self.assertEqual(
            self.app._disclosure_expanded,
            {
                "history": False,
                "verification": False,
                "activity": False,
                "task_tools": False,
            },
        )
        for name in (
            "instructions",
            "summary",
            "apply_button",
            "apply_selected_button",
            "reject_button",
            "edited_files",
            "diff",
        ):
            self.assertNotEqual(getattr(self.app, name).grid_info(), {}, name)

    def test_bundled_window_icon_source_and_runtime_setup(self):
        source = Path(wrapper.WINDOW_ICON_SOURCE)
        expected_source = Path(wrapper.__file__).resolve().parent / "assets" / "code-router.svg"
        self.assertEqual(source.resolve(), expected_source)
        self.assertTrue(source.is_file())
        svg = source.read_text(encoding="utf-8")
        self.assertIn('<title>CodeRouter icon</title>', svg)
        self.assertIn('viewBox="0 0 256 256"', svg)
        self.assertIn('fill="#080808"', svg)
        self.assertIn('stroke="#f3f3f3"', svg)
        self.assertNotIn("Portfolio", str(source))
        self.assertEqual(self.app._window_icon_source, source)
        if self.app._window_icon_image is None:
            self.assertFalse(self.app._window_icon_applied)
        else:
            self.assertTrue(self.app._window_icon_applied)
            self.assertEqual(self.app._window_icon_image.width(), wrapper.WINDOW_ICON_SIZE)
            self.assertEqual(self.app._window_icon_image.height(), wrapper.WINDOW_ICON_SIZE)

    def test_state_and_existing_gate_changes_update_phase_and_next_action(self):
        snapshot = self.activate_snapshot()
        self.app.instructions.delete("1.0", tk.END)
        self.app._update_lifecycle_controls()
        self.assertEqual(self.app.workflow_next_action.get(), "Enter a task prompt")

        self.app.instructions.insert("1.0", "Make the bounded change")
        plan = wrapper.ExecutionPlan(
            "Prepare the bounded change.",
            (wrapper.PlanStep("1", "Review", "Review the current project."),),
        )
        self.app.set_task_state(wrapper.TASK_STATE_PLAN, "Plan ready")
        self.app._set_pending_plan(plan, snapshot.run_id)
        self.assertEqual(self.app.workflow_phase.get(), "PLAN")
        self.assertEqual(self.app.workflow_next_action.get(), "Approve, revise, or cancel plan")

        self.app._clear_pending_plan()
        self.app.inspect_request = wrapper.InspectRequest(
            summary="Need bounded source context",
            paths=("README.md",),
            run_id=snapshot.run_id,
            round=0,
        )
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "Inspect permission required")
        self.assertEqual(self.app.workflow_phase.get(), "RUNNING")
        self.assertEqual(self.app.workflow_next_action.get(), "Allow or deny inspect request")

        self.app._clear_inspect_request()
        self.app.verification_request = wrapper.VerificationRequest(
            command="python -m py_compile sample.py",
            run_id=snapshot.run_id,
        )
        self.app._update_lifecycle_controls()
        self.assertEqual(self.app.workflow_next_action.get(), "Allow or deny verification request")

        self.app._clear_verification_request()
        proposal = wrapper.create_pending_proposal(
            snapshot,
            [{"path": "note.txt", "content": "after"}],
        )
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
        self.app._set_pending_proposal(proposal)
        self.assertEqual(self.app.workflow_phase.get(), "REVIEW")
        self.assertEqual(self.app.workflow_next_action.get(), "Review, apply, or reject changes")

    def test_model_status_and_health_signal_are_reflected_without_model_identity_invention(self):
        self.app.model_status.set("Free queue fallback · next candidate")
        self.app._refresh_workflow_rail()
        self.assertEqual(
            self.app.workflow_model_signal.get(),
            "Free queue fallback · next candidate",
        )

        self.app.model_health.record(
            "known-free-model",
            42,
            wrapper.MODEL_HEALTH_SUCCESS,
            "context fit",
        )
        self.app.model_status.set("Free model fallback")
        self.app._refresh_workflow_rail()
        self.assertIn("Free model fallback", self.app.workflow_model_signal.get())
        self.assertIn("success 42ms", self.app.workflow_model_signal.get())

    def test_rail_refresh_has_no_execution_side_effects_and_preserves_controls(self):
        primary = {
            name: getattr(self.app, name)
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
            )
        }
        before_disclosures = dict(self.app._disclosure_expanded)
        self.app._refresh_workflow_rail()
        self.app._update_lifecycle_controls()
        self.assertEqual(self.app._disclosure_expanded, before_disclosures)
        for name, widget in primary.items():
            self.assertNotEqual(widget.grid_info(), {}, name)
        self.assertIsNone(self.app.pending_proposal)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)


if __name__ == "__main__":
    unittest.main()
