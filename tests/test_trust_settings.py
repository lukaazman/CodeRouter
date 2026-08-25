import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import codex_free_wrapper as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class TrustSettingsUiTests(unittest.TestCase):
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

    def activate_snapshot(self, run_id="trust-settings-run", status=""):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="trust settings test",
            project_instructions="hidden instruction content that must never be displayed",
            project_instructions_status=status,
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        return snapshot

    def test_collapsed_by_default_and_apply_policy_stays_visible(self):
        self.assertFalse(self.app._trust_settings_expanded)
        self.assertEqual(self.app.trust_settings_detail_label.grid_info(), {})
        self.assertNotEqual(self.app.trust_settings_button.grid_info(), {})
        for name in ("review_mode_button", "auto_mode_button"):
            widget = getattr(self.app, name)
            self.assertNotEqual(widget.grid_info(), {}, name)
        self.assertTrue(self.app.permission_note.get())

    def test_click_and_keyboard_round_trip(self):
        button = self.app.trust_settings_button
        button.invoke()
        self.assertTrue(self.app._trust_settings_expanded)
        self.assertNotEqual(self.app.trust_settings_detail_label.grid_info(), {})
        button.invoke()
        self.assertFalse(self.app._trust_settings_expanded)
        self.assertEqual(self.app.trust_settings_detail_label.grid_info(), {})
        self.assertTrue(button.bind("<Return>"))
        self.assertTrue(button.bind("<space>"))
        self.app._toggle_trust_settings_disclosure()
        self.assertTrue(self.app._trust_settings_expanded)
        self.app._toggle_trust_settings_disclosure()
        self.assertFalse(self.app._trust_settings_expanded)

    def test_detail_is_bounded_redacted_and_never_displays_commands_or_content(self):
        secret = "Bearer trust-settings-secret-value"
        self.activate_snapshot(
            status=f"loaded AGENTS.md; Authorization: {secret}"
        )
        self.app.local_command.set("python -c token=trust-settings-secret-value")
        self.app.local_command_result.set("raw command output trust-settings-secret-value")
        self.app._refresh_trust_settings_surface()
        self.app._set_trust_settings_disclosure(True)

        detail = self.app.trust_settings_detail_text.get()
        self.assertIn("Apply mode: Review changes", detail)
        self.assertIn("Project instructions:", detail)
        self.assertIn("Local command policy:", detail)
        self.assertLessEqual(len(detail), wrapper.TRUST_SETTINGS_MAX_CHARS)
        self.assertNotIn("trust-settings-secret-value", detail)
        self.assertNotIn("raw command output", detail)
        self.assertNotIn("hidden instruction content", detail)

    def test_refresh_tracks_mode_snapshot_and_permission_metadata(self):
        self.app.apply_mode.set(wrapper.APPLY_MODE_AUTO)
        self.app._on_apply_mode_changed()
        self.assertIn("Apply mode: Auto-apply", self.app.trust_settings_detail_text.get())

        snapshot = self.activate_snapshot(
            "trust-settings-snapshot",
            "loaded AGENTS.md (24 bytes, UTF-8); loaded 1 descendant AGENTS.md file(s)",
        )
        self.app._refresh_trust_settings_surface()
        detail = self.app.trust_settings_detail_text.get()
        self.assertIn("Project instructions: loaded AGENTS.md", detail)
        self.assertNotIn("no active snapshot", detail)

        decision = self.app._record_permission_decision(
            "inspect",
            wrapper.PERMISSION_DECISION_DENY,
            run_id=snapshot.run_id,
        )
        self.assertIsNotNone(decision)
        detail = self.app.trust_settings_detail_text.get()
        self.assertIn("Permission decisions: 1 recorded", detail)
        self.assertIn("inspect:deny", detail)

    def test_pending_permission_auto_opens_but_normal_state_stays_collapsed(self):
        snapshot = self.activate_snapshot("trust-settings-pending")
        self.app.inspect_request = wrapper.InspectRequest(
            summary="Need one bounded file",
            paths=("README.md",),
            run_id=snapshot.run_id,
            round=0,
        )
        self.app._update_lifecycle_controls()
        self.assertTrue(self.app._trust_settings_expanded)
        self.assertNotEqual(self.app.trust_settings_detail_label.grid_info(), {})

        self.app.inspect_request = None
        self.app._set_trust_settings_disclosure(False)
        self.app._update_lifecycle_controls()
        self.assertFalse(self.app._trust_settings_expanded)

        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)
        self.assertIsNone(self.app.pending_proposal)


if __name__ == "__main__":
    unittest.main()
