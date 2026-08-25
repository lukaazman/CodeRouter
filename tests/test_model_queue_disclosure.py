import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import codex_free_wrapper as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ModelQueueDisclosureUiTests(unittest.TestCase):
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

    def test_default_collapsed_and_rail_remains_visible(self):
        self.assertNotEqual(self.app.workflow_rail.grid_info(), {})
        self.assertFalse(self.app._model_queue_expanded)
        self.assertEqual(self.app.workflow_model_detail.grid_info(), {})
        self.assertEqual(
            self.app.workflow_model_disclosure_label.get(),
            "▸ MODEL / QUEUE",
        )

    def test_click_and_keyboard_round_trip_without_recreating_widgets(self):
        detail_widget = self.app.workflow_model_detail
        disclosure = self.app.workflow_model_disclosure_button

        disclosure.invoke()
        self.app.update_idletasks()
        self.assertTrue(self.app._model_queue_expanded)
        self.assertNotEqual(detail_widget.grid_info(), {})

        disclosure.invoke()
        self.app.update_idletasks()
        self.assertFalse(self.app._model_queue_expanded)
        self.assertEqual(detail_widget.grid_info(), {})
        self.assertTrue(disclosure.bind("<Return>"))
        self.assertTrue(disclosure.bind("<space>"))
        self.app._toggle_model_queue_disclosure()
        self.assertTrue(self.app._model_queue_expanded)
        self.app._toggle_model_queue_disclosure()
        self.assertFalse(self.app._model_queue_expanded)
        self.assertIs(detail_widget, self.app.workflow_model_detail)

    def test_fallback_queue_and_health_metadata_are_rendered(self):
        self.app.model_status.set("")
        self.app._refresh_workflow_rail()
        self.app._set_model_queue_disclosure(True)
        detail = self.app.workflow_model_detail_text.get()
        self.assertIn("Fallback queue:", detail)
        for model in wrapper.MODEL_FALLBACKS:
            self.assertIn(model, detail)
        self.assertIn("Health: none recorded", detail)

        self.app.model_health.record(
            "known-free-model",
            42,
            wrapper.MODEL_HEALTH_SUCCESS,
            "context fit",
        )
        self.app._refresh_workflow_rail()
        detail = self.app.workflow_model_detail_text.get()
        self.assertIn("known-free-model", detail)
        self.assertIn("success 42ms", detail)
        self.assertIn("context fit", detail)

    def test_model_status_refresh_is_redacted_and_metadata_only(self):
        self.app._set_model_queue_disclosure(True)
        self.app.model_status.set("Trying free model · Authorization: Bearer secret-token-value")
        self.app._refresh_workflow_rail()
        detail = self.app.workflow_model_detail_text.get()
        self.assertIn("Trying free model", detail)
        self.assertNotIn("secret-token-value", detail)
        self.assertIn("[redacted]", detail)

    def test_active_run_does_not_auto_hide_details_or_start_resources(self):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id="model-queue-disclosure-run",
            request_text="model queue disclosure test",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._set_model_queue_disclosure(True)
        self.app.model_status.set("Trying explicitly free model")
        self.app._update_lifecycle_controls()

        self.assertTrue(self.app._model_queue_expanded)
        self.assertNotEqual(self.app.workflow_model_detail.grid_info(), {})
        self.assertIn("Run: active", self.app.workflow_model_detail_text.get())
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)
        self.assertNotEqual(self.app.instructions.grid_info(), {})
        self.assertNotEqual(self.app.apply_button.grid_info(), {})


if __name__ == "__main__":
    unittest.main()
