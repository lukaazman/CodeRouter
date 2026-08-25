import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class EvidenceHandoffTests(unittest.TestCase):
    def make_snapshot(self, root, plan=None):
        return wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="run-handoff-1",
            task_id="task-handoff-1",
            request_text="Review the bounded executor result.",
            approved_plan=plan,
        )

    def valid_response(self):
        return {
            "status": "approved",
            "summary": "Evidence is bounded and ready for inspection.",
            "next_step": {
                "title": "Review evidence",
                "detail": "Inspect the evidence and confirm the next prompt manually.",
                "scope": ["executor evidence"],
                "requires_user_confirmation": True,
            },
        }

    def test_handoff_is_immutable_bounded_and_material_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = wrapper.ExecutionPlan(
                "Bounded plan",
                (wrapper.PlanStep("1", "Inspect", "Review metadata only"),),
            )
            handoff = wrapper.build_evidence_handoff(
                self.make_snapshot(root, plan),
                changed_paths=[
                    {"path": "src/app.py", "additions": 4, "deletions": 2},
                    {"path": ".env", "additions": 100, "deletions": 100},
                    {"path": "../outside.py", "additions": 1, "deletions": 1},
                ],
                model_statuses=["Selected free model: qwen/test"],
                verification_statuses=["stdout: raw file contents", "Bearer sk-or-v1-123456789"],
                acceptance_evidence=["diff --git a/src/app.py b/src/app.py"],
                run_sequence=999999,
            )
            self.assertIsInstance(handoff, wrapper.EvidenceHandoff)
            self.assertEqual(handoff.changed_paths[0].relative_path, "src/app.py")
            self.assertEqual(handoff.run_sequence, wrapper.HANDOFF_MAX_COUNT)
            self.assertNotIn(".env", handoff.to_json())
            self.assertNotIn("raw file contents", handoff.to_json())
            self.assertNotIn("sk-or-v1-123456789", handoff.to_json())
            self.assertNotIn("diff --git", handoff.to_json())
            with self.assertRaises(Exception):
                handoff.executor_task_id = "changed"

    def test_strict_read_only_overseer_json(self):
        review = wrapper.parse_overseer_response(self.valid_response())
        self.assertEqual(review.status, "approved")
        self.assertTrue(review.next_step.requires_user_confirmation)
        self.assertEqual(set(json.loads(review.to_json())), {"status", "summary", "next_step"})

    def test_malformed_secret_edit_command_and_permission_responses_fail_closed(self):
        bad_responses = [
            {},
            {**self.valid_response(), "extra": "value"},
            json.dumps({**self.valid_response(), "summary": "api_key=sk-or-v1-123456789"}),
            json.dumps({**self.valid_response(), "summary": "run python verification"}),
            json.dumps({**self.valid_response(), "next_step": {**self.valid_response()["next_step"], "detail": "write a file"}}),
            json.dumps({**self.valid_response(), "next_step": {**self.valid_response()["next_step"], "requires_user_confirmation": False}}),
        ]
        for response in bad_responses:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    wrapper.parse_overseer_response(response)

    def test_local_adapter_is_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            handoff = wrapper.build_evidence_handoff(self.make_snapshot(Path(temp)))
        first = wrapper.parse_overseer_response(wrapper.local_overseer_adapter(handoff))
        second = wrapper.parse_overseer_response(wrapper.local_overseer_adapter(handoff))
        self.assertEqual(first, second)
        self.assertEqual(first.status, "approved")
        self.assertTrue(first.next_step.requires_user_confirmation)

    def test_stale_handoff_is_not_accepted_by_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            handoff = wrapper.build_evidence_handoff(self.make_snapshot(Path(temp)))
        self.assertEqual(handoff.executor_run_id, "run-handoff-1")
        self.assertNotEqual(handoff.executor_run_id, "stale-run")


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class OverseerUiBoundaryTests(unittest.TestCase):
    def test_send_and_approve_only_prefill_and_never_start_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            try:
                app = wrapper.CodeAgentApp(
                    history_path=Path(temp) / "history.json",
                    overseer_adapter=lambda _handoff: EvidenceHandoffTests().valid_response(),
                )
            except wrapper.tk.TclError as exc:
                self.skipTest(f"Tk unavailable: {exc}")
            try:
                root = Path(temp)
                app._handoff_snapshot = EvidenceHandoffTests().make_snapshot(root)
                app._handoff_created_at = "2026-01-01T00:00:00+00:00"
                app._handoff_stale = False
                app.run_timeline = []
                review = app.send_handoff_to_overseer()
                self.assertEqual(review.status, "approved")
                with mock.patch.object(app, "run_agent") as run_agent, mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
                    self.assertTrue(app.approve_overseer_next_step())
                run_agent.assert_not_called()
                self.assertIn("Review evidence", app.instructions.get("1.0", wrapper.tk.END))
                app._handoff_stale = True
                app.overseer_review = None
                self.assertIsNone(app.send_handoff_to_overseer())
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
