import os
import tkinter as tk
import unittest
from unittest import mock

import CodeRouter as wrapper
import ui_kit
from tests.ui_test_helpers import build_hidden_app


class UiKitTests(unittest.TestCase):
    def test_motion_preference_defaults_to_full_motion(self):
        with mock.patch.dict(os.environ, {"CODEROUTER_REDUCED_MOTION": ""}):
            self.assertFalse(ui_kit.reduced_motion())
            self.assertFalse(ui_kit.reduced_motion("full"))
            self.assertTrue(ui_kit.reduced_motion("reduced"))
        with mock.patch.dict(os.environ, {"CODEROUTER_REDUCED_MOTION": "1"}):
            self.assertTrue(ui_kit.reduced_motion("full"))

    def test_color_mix_and_path_slice(self):
        self.assertEqual(ui_kit.mix("#000000", "#ffffff", 0.5), "#808080")
        path = [(0, 0), (10, 0), (10, 10)]
        self.assertEqual(ui_kit.path_length(path), 20)
        self.assertEqual(ui_kit.path_slice(path, 5, 15), [(5.0, 0.0), (10, 0), (10.0, 5.0)])
        self.assertEqual(ui_kit.path_slice(path, 15, 5), [])


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class VisualLayerTests(unittest.TestCase):
    def setUp(self):
        self.app = build_hidden_app(wrapper)

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()

    def test_icons_render_at_requested_size_and_are_cached(self):
        first = self.app.icons.get("folder", 18, "#ffffff", "#000000")
        self.assertEqual(first.width(), self.app._px(18))
        self.assertIs(first, self.app.icons.get("folder", 18, "#ffffff", "#000000"))

    def test_reduced_animator_applies_tweens_immediately(self):
        animator = ui_kit.Animator(self.app, reduce=True)
        seen = []
        animator.tween("x", 1.0, seen.append, done=lambda: seen.append("done"))
        self.assertEqual(seen, [1.0, "done"])
        animator.close()

    def test_empty_state_follows_conversation_content(self):
        self.assertTrue(self.app.empty_state.winfo_manager())
        self.app.set_summary("Updated two files.")
        self.assertFalse(self.app.empty_state.winfo_manager())
        self.app.set_summary("New chat started. Previous model context cleared.")
        self.assertTrue(self.app.empty_state.winfo_manager())

    def test_prompt_is_empty_with_placeholder_and_starters_never_overwrite(self):
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "")
        self.assertTrue(self.app.prompt_placeholder.winfo_manager())
        self.app._prefill_prompt("Add tests for ")
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "Add tests for ")
        self.assertFalse(self.app.prompt_placeholder.winfo_manager())
        self.app._prefill_prompt("Refactor ")
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "Add tests for ")

    def test_phase_stepper_tracks_task_state(self):
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review ready")
        self.app._refresh_workflow_rail()
        self.assertEqual(self.app._stepper_state, wrapper.TASK_STATE_REVIEW)
        self.assertEqual(self.app.status_detail_label.cget("text"), "Review ready")

    def test_stop_button_only_shows_while_cancellable(self):
        self.app._update_lifecycle_controls()
        self.assertEqual(self.app.stop_button.grid_info(), {})
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "mock")
        self.app._update_lifecycle_controls()
        self.assertNotEqual(self.app.stop_button.grid_info(), {})

    def test_escape_closes_drawer_when_nothing_is_pending(self):
        self.app._show_utility_view("history")
        self.assertEqual(self.app._utility_drawer_view, "history")
        self.app._on_escape_shortcut(None)
        self.assertIsNone(self.app._utility_drawer_view)
        self.assertEqual(self.app._legacy_sidebar.grid_info(), {})

    def test_narrow_window_collapses_idle_inspector_and_restores_it(self):
        self.app.deiconify()
        self.app.geometry("900x640")
        self.app.update()
        self.app._apply_breakpoints()
        self.assertTrue(self.app._review_inspector_collapsed)
        self.app.geometry("1440x900")
        self.app.update()
        self.app._apply_breakpoints()
        self.assertFalse(self.app._review_inspector_collapsed)


if __name__ == "__main__":
    unittest.main()
