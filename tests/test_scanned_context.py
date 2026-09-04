import os
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import CodeRouter as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ScannedContextUiTests(unittest.TestCase):
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
        self.external_dir = tempfile.TemporaryDirectory()
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
        self.external_dir.cleanup()

    def test_default_collapsed_and_keyboard_round_trip_preserves_widgets(self):
        button = self.app.scanned_context_disclosure_button
        detail = self.app.scanned_context_detail_label
        self.assertFalse(self.app._scanned_context_expanded)
        self.assertEqual(detail.grid_info(), {})
        self.assertEqual(button.cget("text"), "▸ Scan map")

        button.invoke()
        self.assertTrue(self.app._scanned_context_expanded)
        self.assertNotEqual(detail.grid_info(), {})
        button.invoke()
        self.assertFalse(self.app._scanned_context_expanded)
        self.assertEqual(detail.grid_info(), {})
        self.assertTrue(button.bind("<Return>"))
        self.assertTrue(button.bind("<space>"))
        self.app._toggle_scanned_context_disclosure()
        self.assertTrue(self.app._scanned_context_expanded)
        self.app._toggle_scanned_context_disclosure()
        self.assertFalse(self.app._scanned_context_expanded)
        self.assertIs(self.app.scanned_context_detail_label, detail)

    def test_successful_scan_renders_bounded_relative_metadata_only(self):
        root = Path(self.project_dir.name)
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("print('project content')", encoding="utf-8")
        (root / "secret-token.txt").write_text("token = should-not-be-shown", encoding="utf-8")
        external = Path(self.external_dir.name) / "notes.txt"
        external.write_text("Authorization: Bearer should-not-be-shown", encoding="utf-8")

        self.app.selected_folder.set(str(root))
        self.app.extra_context_paths = [str(external)]
        self.assertTrue(self.app.scan_folder(silent=True))
        self.app._set_scanned_context_disclosure(True)
        detail = self.app.scanned_context_detail_text.get()

        self.assertIn("Scanned:", detail)
        self.assertIn("shown:", detail)
        self.assertIn("src/main.py", detail)
        self.assertIn(wrapper.EXTERNAL_CONTEXT_PREFIX, detail)
        self.assertNotIn(str(root), detail)
        self.assertNotIn(str(external), detail)
        self.assertNotIn("project content", detail)
        self.assertNotIn("Authorization", detail)
        self.assertNotIn("should-not-be-shown", detail)
        self.assertNotIn("secret-token.txt", detail)
        self.assertLessEqual(len(detail), wrapper.SCANNED_CONTEXT_MAX_CHARS)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)

    def test_unavailable_or_changed_scan_clears_old_paths_without_rescanning(self):
        root = Path(self.project_dir.name)
        (root / "README.md").write_text("readme", encoding="utf-8")
        self.app.selected_folder.set(str(root))
        self.assertTrue(self.app.scan_folder(silent=True))
        self.assertIn("README.md", self.app._scanned_context_paths)

        missing = root / "missing-project"
        self.app.selected_folder.set(str(missing))
        self.assertFalse(self.app.scan_folder(silent=True))
        self.assertEqual(self.app._scanned_context_paths, ())
        self.assertEqual(self.app.scanned_context_detail_text.get(), "No current successful scan.")

        self.app.selected_folder.set(str(root))
        self.assertTrue(self.app.scan_folder(silent=True))
        self.assertIn("README.md", self.app._scanned_context_paths)
        self.app.extra_context_paths = [str(Path(self.external_dir.name) / "changed.txt")]
        self.app._refresh_scanned_context_preview()
        self.assertEqual(self.app._scanned_context_paths, ())
        self.assertEqual(self.app.scanned_context_detail_text.get(), "No current successful scan.")

    def test_preview_refresh_is_read_only_and_does_not_start_resources(self):
        root = Path(self.project_dir.name)
        (root / "main.py").write_text("pass", encoding="utf-8")
        self.app.selected_folder.set(str(root))
        self.assertTrue(self.app.scan_folder(silent=True))
        self.app._set_scanned_context_disclosure(True)
        before = self.app._scanned_context_paths
        self.app._refresh_scanned_context_preview()
        self.assertEqual(self.app._scanned_context_paths, before)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)
        self.assertIsNone(self.app.pending_proposal)

    def test_preview_clears_when_scanned_root_becomes_a_non_directory(self):
        root = Path(self.project_dir.name) / "selected-project"
        root.mkdir()
        (root / "main.py").write_text("pass", encoding="utf-8")
        self.app.selected_folder.set(str(root))
        self.assertTrue(self.app.scan_folder(silent=True))
        self.assertIn("main.py", self.app._scanned_context_paths)

        shutil.rmtree(root)
        root.write_text("the selected root is no longer a directory", encoding="utf-8")
        self.app._refresh_scanned_context_preview()

        self.assertEqual(self.app._scanned_context_paths, ())
        self.assertIsNone(self.app._scanned_context_root)
        self.assertEqual(self.app.scanned_context_detail_text.get(), "No current successful scan.")


if __name__ == "__main__":
    unittest.main()
