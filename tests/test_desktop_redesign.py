import tempfile
import unittest
from pathlib import Path
import CodeRouter as c

class DesktopRedesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = c.CodeAgentApp(history_path=Path(self.temp.name) / 'history.json')
    def tearDown(self):
        self.app.on_close()
        self.temp.cleanup()
    def test_review_collapse_preserves_text_and_selection(self):
        self.app.write_diff('diff --git a/a.py b/a.py\n+example\n')
        before = self.app.diff.get('1.0', 'end')
        self.app._set_review_inspector_collapsed(True)
        self.assertNotIn(str(self.app._right_panel), self.app.workbench_main.panes())
        self.app._set_review_inspector_collapsed(False)
        self.assertIn(str(self.app._right_panel), self.app.workbench_main.panes())
        self.assertEqual(before, self.app.diff.get('1.0', 'end'))
    def test_pending_plan_reveals_hidden_inspector(self):
        self.app._set_review_inspector_collapsed(True)
        self.app.pending_plan = object()
        self.app._auto_open_disclosures()
        self.assertFalse(self.app._review_inspector_collapsed)
        self.assertTrue(self.app._disclosure_expanded['task_tools'])
        self.app.pending_plan = None
    def test_drawer_navigation_preserves_prompt_and_history_widget(self):
        history = self.app.history_list
        self.app.instructions.insert('end', ' preserve this task')
        before = self.app.instructions.get('1.0', 'end')
        for view in ('workspace', 'history', 'verification', 'settings'):
            self.app._show_utility_view(view)
            self.assertTrue(self.app._legacy_sidebar.grid_info())
            self.assertIs(history, self.app.history_list)
        self.app._set_utility_drawer(None)
        self.assertEqual(before, self.app.instructions.get('1.0', 'end'))
    def test_compact_review_actions_fit_at_default_size(self):
        self.app.deiconify()
        self.app.update()
        for button in (self.app.apply_button, self.app.apply_selected_button, self.app.reject_button):
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
        self.assertGreater(self.app._center_panel.winfo_width(), self.app._right_panel.winfo_width())

if __name__ == '__main__': unittest.main()
