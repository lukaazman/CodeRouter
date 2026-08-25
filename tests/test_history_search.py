import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper
from tests.ui_test_helpers import build_hidden_app


def make_record(root, task_id, request, outcome, state):
    timestamp = "2026-08-25T10:00:00+00:00"
    return wrapper.HistoryRecord(
        task_id=task_id,
        project_root=str(root),
        request_summary=request,
        plan_summary="Bounded plan",
        plan_steps=(wrapper.PlanStep("1", "Inspect", "Read metadata only."),),
        selected_model="free/test-model",
        state_transitions=((state, "History state", timestamp),),
        reasons=("safe metadata",),
        outcome=outcome,
        created_at=timestamp,
        updated_at=timestamp,
    )


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class HistorySearchUiTests(unittest.TestCase):
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
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        self.history_path = Path(self.temp_dir.name) / "history.json"
        self.app = build_hidden_app(wrapper, history_path=self.history_path)
        self.records = (
            make_record(self.root, "ui-task", "Update the desktop UI", wrapper.TASK_STATE_REVIEW, wrapper.TASK_STATE_REVIEW),
            make_record(self.root, "parser-task", "Fix the parser error", wrapper.TASK_STATE_APPLIED, wrapper.TASK_STATE_APPLIED),
        )
        for record in self.records:
            self.assertTrue(self.app.history_store.append(record))
        self.app._refresh_history_browser()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def open_history(self):
        self.app.history_disclosure_button.invoke()
        self.app.update_idletasks()

    def test_collapsed_default_and_existing_widgets_are_preserved(self):
        history_list = self.app.history_list
        history_detail = self.app.history_detail
        history_frame = self.app._disclosure_widgets["history"][0]
        self.assertFalse(self.app._disclosure_expanded["history"])
        self.assertEqual(history_frame.grid_info(), {})
        self.assertFalse(history_frame.winfo_ismapped())
        self.assertIs(self.app.history_list, history_list)
        self.assertIs(self.app.history_detail, history_detail)
        self.assertEqual(
            [record.task_id for record in self.app._history_browser_records],
            ["parser-task", "ui-task"],
        )

    def test_case_insensitive_filter_and_clear_restore_newest_first_list(self):
        self.open_history()
        list_widget = self.app.history_list
        detail_widget = self.app.history_detail
        original_disk = self.history_path.read_bytes()
        self.app.history_search_entry.insert(0, "PARSER")
        self.app._on_history_search_changed()

        self.assertEqual(
            [record.task_id for record in self.app._history_browser_records],
            ["parser-task"],
        )
        self.assertEqual(self.app.history_filter_status.get(), "1 match · metadata-only filter")
        self.assertEqual(self.app.history_list.size(), 1)
        self.assertIs(self.app.history_list, list_widget)
        self.assertIs(self.app.history_detail, detail_widget)
        self.assertEqual(self.history_path.read_bytes(), original_disk)
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)

        self.app.history_search_entry.delete(0, tk.END)
        self.app._on_history_search_changed()
        self.assertEqual(
            [record.task_id for record in self.app._history_browser_records],
            ["parser-task", "ui-task"],
        )
        self.assertEqual(self.app.history_filter_status.get(), "2 saved tasks · newest first")

    def test_no_match_clears_stale_selection_and_detail(self):
        self.open_history()
        self.assertIsNotNone(self.app.selected_history_record)
        self.assertIn("Task id:", self.app.history_detail.get("1.0", tk.END))

        self.app.history_search_entry.insert(0, "does-not-exist")
        self.app._on_history_search_changed()

        self.assertEqual(self.app.history_list.size(), 0)
        self.assertEqual(self.app._history_browser_records, [])
        self.assertIsNone(self.app.selected_history_record)
        self.assertEqual(self.app.history_detail.get("1.0", tk.END).strip(), "")
        self.assertIn("no history matches", self.app.history_status.get().lower())
        self.assertIn("0 matches", self.app.history_filter_status.get())

        self.app.history_search_entry.delete(0, tk.END)
        self.app._on_history_search_changed()
        self.assertEqual(self.app.history_list.size(), 2)
        self.assertIsNotNone(self.app.selected_history_record)

    def test_redacted_bounded_metadata_filter_is_inspection_only(self):
        self.open_history()
        secret = "sk-or-v1-history-search-secret-123456"
        raw_query = f"Authorization: Bearer {secret} " + ("x" * 200)
        with (
            mock.patch.object(wrapper.threading, "Thread") as thread_class,
            mock.patch.object(wrapper.subprocess, "Popen") as popen,
            mock.patch.object(self.app.history_store, "upsert") as upsert,
            mock.patch.object(self.app, "resume_selected_history") as resume,
        ):
            self.app.history_search_entry.insert(0, raw_query)
            self.app._on_history_search_changed()
            self.assertNotIn(secret, self.app.history_search_query.get())
            self.assertNotIn(secret, self.app.history_filter_status.get())

            self.app.history_search_entry.delete(0, tk.END)
            self.app._on_history_search_changed()
            self.app.history_list.selection_clear(0, tk.END)
            self.app.history_list.selection_set(0)
            self.app._on_history_selected()

        self.assertLessEqual(
            len(self.app.history_search_query.get()),
            wrapper.HISTORY_SEARCH_MAX_CHARS,
        )
        self.assertNotIn(secret, self.app.history_search_query.get())
        self.assertNotIn(secret, self.app.history_filter_status.get())
        self.assertNotIn(secret, self.app.history_detail.get("1.0", tk.END))
        self.assertIsNotNone(self.app.selected_history_record)
        thread_class.assert_not_called()
        popen.assert_not_called()
        upsert.assert_not_called()
        resume.assert_not_called()
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)


if __name__ == "__main__":
    unittest.main()
