import os
import tkinter as tk
import unittest
from unittest import mock

import CodeRouter as wrapper
from tests.ui_test_helpers import build_hidden_app


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class WorkbenchScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.app = build_hidden_app(wrapper)

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()

    def test_workbench_viewport_preserves_horizontal_paned_window(self):
        self.assertTrue(self.app.workbench_canvas.winfo_exists())
        self.assertTrue(self.app.workbench_scrollbar.winfo_exists())
        self.assertTrue(self.app.workbench_body.winfo_exists())
        self.assertEqual(str(self.app.workbench_main.cget("orient")), tk.HORIZONTAL)
        self.assertEqual(self.app.workbench_canvas.itemcget(self.app._workbench_window_id, "window"), str(self.app.workbench_body))

    def test_overflow_sync_is_deterministic_and_scrollbar_is_conditional(self):
        self.app.geometry("1180x720")
        self.app.update_idletasks()
        self.app._sync_workbench_scrollregion()
        self.app.update_idletasks()
        first_region = self.app.workbench_canvas.cget("scrollregion")
        first_visible = self.app._workbench_scrollbar_visible

        self.app._sync_workbench_scrollregion()
        self.app.update_idletasks()
        self.assertEqual(self.app.workbench_canvas.cget("scrollregion"), first_region)
        self.assertEqual(self.app._workbench_scrollbar_visible, first_visible)

        with mock.patch.object(self.app.workbench_canvas, "winfo_height", return_value=2000):
            self.app._sync_workbench_scrollregion()
            self.app.update_idletasks()
        self.assertFalse(self.app._workbench_scrollbar_visible)
        self.assertEqual(self.app.workbench_scrollbar.grid_info(), {})
        self.assertEqual(self.app.workbench_canvas.yview()[0], 0.0)


if __name__ == "__main__":
    unittest.main()
