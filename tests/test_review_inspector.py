import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

import CodeRouter as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ReviewInspectorUiTests(unittest.TestCase):
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

    def prepare_two_file_review(self):
        root = Path(self.project_dir.name)
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id="review-inspector-run",
            request_text="review inspector test",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        proposal = wrapper.create_pending_proposal(
            snapshot,
            [
                {"path": "first.txt", "content": "first replacement\n"},
                {"path": "second.txt", "content": "second replacement\n"},
            ],
        )
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
        self.app._set_pending_proposal(proposal)
        self.app.diff_by_path = wrapper.render_diff_by_path(
            root,
            [{"path": "first.txt", "content": "first replacement\n"},
             {"path": "second.txt", "content": "second replacement\n"}],
        )
        self.app.populate_changed_files(wrapper.build_file_rows(self.app.diff_by_path))
        return snapshot

    def test_empty_selection_metadata_is_visible(self):
        self.assertNotEqual(self.app.review_selection_meta_label.grid_info(), {})
        self.assertEqual(
            self.app.review_selection_meta.get(),
            "Selected 0 of 0 · no file selected",
        )

    def test_empty_state_rows_clear_round_trip_preserves_widget_identity(self):
        edited_files = self.app.edited_files
        diff = self.app.diff
        diff_pane = self.app.review_diff_pane
        empty_state = self.app.review_empty_state

        self.assertNotEqual(empty_state.grid_info(), {})
        self.assertEqual(diff_pane.grid_info(), {})
        self.assertEqual(tuple(edited_files.get_children()), ())

        self.app.diff_by_path = {
            "first.txt": "--- FILE first.txt ---\n+replacement\n",
        }
        self.app.populate_changed_files([{"path": "first.txt", "stats": "+1 / -0"}])
        self.assertEqual(empty_state.grid_info(), {})
        self.assertNotEqual(diff_pane.grid_info(), {})
        self.assertEqual(tuple(edited_files.get_children()), ("first.txt",))
        self.assertIn("first.txt", diff.get("1.0", tk.END))

        self.app.clear_changed_files()
        self.assertNotEqual(empty_state.grid_info(), {})
        self.assertEqual(diff_pane.grid_info(), {})
        self.assertEqual(tuple(edited_files.get_children()), ())
        self.assertIs(edited_files, self.app.edited_files)
        self.assertIs(diff, self.app.diff)
        self.assertIs(diff_pane, self.app.review_diff_pane)
        self.assertIs(empty_state, self.app.review_empty_state)
    def test_two_changed_files_show_selection_count_and_inspected_path(self):
        self.prepare_two_file_review()
        self.assertEqual(
            self.app.review_selection_meta.get(),
            "Selected 1 of 2 · inspecting first.txt",
        )
        self.assertEqual(tuple(self.app.edited_files.selection()), ("first.txt",))

    def test_extended_selection_preserves_both_items_and_apply_selected_state(self):
        self.prepare_two_file_review()
        self.app.edited_files.selection_add("second.txt")
        self.app.on_file_selected(None)
        self.assertEqual(
            tuple(self.app.edited_files.selection()),
            ("first.txt", "second.txt"),
        )
        self.assertEqual(
            self.app.review_selection_meta.get(),
            "Selected 2 of 2 · inspecting first.txt",
        )
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.NORMAL)

    def test_selection_and_diff_round_trip_preserve_widgets_and_content(self):
        self.prepare_two_file_review()
        edited_files = self.app.edited_files
        diff = self.app.diff
        first_diff = diff.get("1.0", tk.END)
        self.assertIn("first.txt", first_diff)

        edited_files.selection_set("second.txt")
        self.app.on_file_selected(None)
        second_diff = diff.get("1.0", tk.END)
        self.assertIn("second.txt", second_diff)
        self.assertIs(edited_files, self.app.edited_files)
        self.assertIs(diff, self.app.diff)

        edited_files.selection_set("first.txt")
        self.app.on_file_selected(None)
        self.assertEqual(diff.get("1.0", tk.END), first_diff)
        self.assertEqual(
            self.app.review_selection_meta.get(),
            "Selected 1 of 2 · inspecting first.txt",
        )

    def test_inspector_refresh_has_no_worker_provider_or_process_side_effects(self):
        self.prepare_two_file_review()
        self.app._refresh_review_selection_meta()
        self.app._update_lifecycle_controls()
        self.assertIsNotNone(self.app.pending_proposal)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)


if __name__ == "__main__":
    unittest.main()
