import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


class VerificationParserTests(unittest.TestCase):
    def test_verify_is_a_strict_action_separate_from_final_and_inspect(self):
        request = wrapper.parse_executor_response(
            json.dumps({"action": "verify", "command": "python -m pytest tests"})
        )
        self.assertIsInstance(request, wrapper.VerificationRequest)
        self.assertEqual(request.command, "python -m pytest tests")
        self.assertEqual(request.to_dict()["action"], "verify")

        for payload in (
            {"action": "verify", "command": "python -m pytest tests", "files": []},
            {"action": "verify", "command": "cmd /c pytest"},
            {"action": "verify", "command": "python -m pytest; whoami"},
            {"action": "verify", "command": "Authorization: Bearer raw-value"},
            {"action": "verify", "command": ""},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    wrapper.parse_executor_response(json.dumps(payload))

    def test_verify_command_uses_existing_policy_without_starting_anything(self):
        self.assertEqual(wrapper.verification_command_policy(("python", "-m", "pytest")), "allowed")
        self.assertEqual(wrapper.verification_command_policy(("custom-checker",)), "unknown")
        self.assertEqual(wrapper.verification_command_policy(("powershell", "-Command", "x")), "blocked")
        with self.assertRaises(ValueError):
            wrapper.VerificationRequest("powershell -Command x")


class VerificationWorkerContractTests(unittest.TestCase):
    class Host:
        def __init__(self, root, run_id="verify-run"):
            self.api_key = "worker-key-123456"
            self.work_queue = queue.Queue()
            self.lifecycle = wrapper.RunLifecycle()
            self.snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id=run_id,
                request_text="request verification",
            )
            self.lifecycle.activate(self.snapshot)

        def _run_is_current(self, run_id):
            return self.lifecycle.accepts(run_id)

    @staticmethod
    def drain(host):
        events = []
        while True:
            try:
                events.append(host.work_queue.get_nowait())
            except queue.Empty:
                return events

    def test_model_verify_request_emits_permission_only_and_never_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "sentinel.txt"
            target.write_text("original", encoding="utf-8")
            host = self.Host(root)
            requested = wrapper.VerificationRequest("python -m pytest tests", host.snapshot.run_id)
            provider = mock.Mock(return_value=(requested, "safe:free"))
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", provider),
            ):
                wrapper.CodeAgentApp._run_agent_worker(
                    host,
                    host.snapshot,
                    host.snapshot.request_text,
                    None,
                    True,
                )
            events = self.drain(host)
            kinds = [event.kind for event in events]
            self.assertIn("verification_request", kinds)
            self.assertNotIn("proposal", kinds)
            self.assertNotIn("diffs", kinds)
            self.assertNotIn("auto_apply", kinds)
            payload = next(event.payload for event in events if event.kind == "verification_request")
            self.assertIsInstance(payload, wrapper.VerificationRequest)
            self.assertEqual(payload.run_id, host.snapshot.run_id)
            provider.assert_called_once()
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_second_verify_request_is_rejected_after_one_round(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = self.Host(Path(temp_dir))
            snapshot = wrapper.create_run_snapshot(
                temp_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id=host.snapshot.run_id,
                request_text="request verification",
                verification_round=1,
            )
            requested = wrapper.VerificationRequest("python -m pytest tests", snapshot.run_id)
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=(requested, "safe:free")),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, snapshot.request_text, None, True)
            events = self.drain(host)
            self.assertNotIn("verification_request", [event.kind for event in events])
            self.assertNotIn("proposal", [event.kind for event in events])
            self.assertTrue(any(event.kind == "task_state" and event.payload[0] == wrapper.TASK_STATE_ERROR for event in events))


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class VerificationPermissionUiTests(unittest.TestCase):
    def make_app(self, root):
        return wrapper.CodeAgentApp(history_path=root / "history.json")

    def prepare_request(self, app, root, run_id="verification-ui"):
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_AUTO,
            run_id=run_id,
            request_text="request verification",
        )
        app.selected_folder.set(str(root))
        app.lifecycle.activate(snapshot)
        app.run_resources.create(snapshot.run_id)
        app.run_snapshot = snapshot
        app.task_state = wrapper.TASK_STATE_RUNNING
        request = wrapper.VerificationRequest("python -m pytest tests", snapshot.run_id)
        app.verification_request = request
        app._write_verification_request_preview(request)
        return snapshot, request

    def test_allow_revalidates_and_starts_existing_runner_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "sentinel.txt"
            target.write_text("original", encoding="utf-8")
            app = self.make_app(root)
            try:
                snapshot, request = self.prepare_request(app, root, "allow-verification")
                with (
                    mock.patch.object(app, "_start_verification_worker") as runner,
                    mock.patch.object(app, "_start_run_worker") as next_worker,
                ):
                    self.assertTrue(app.allow_verification())
                runner.assert_called_once_with(
                    ("python", "-m", "pytest", "tests"),
                    root,
                    policy_confirmed=False,
                    continuation_run_id=snapshot.run_id,
                )
                next_worker.assert_not_called()
                self.assertIsNone(app.verification_request)
                self.assertEqual(app.lifecycle.active_snapshot.verification_round, 1)
                self.assertEqual(app.lifecycle.active_snapshot.apply_mode, wrapper.APPLY_MODE_REVIEW)
                self.assertEqual(app.task_state, wrapper.TASK_STATE_RUNNING)
                app.verification_request = wrapper.VerificationRequest(request.command, snapshot.run_id)
                self.assertFalse(app.allow_verification())
                self.assertIsNone(app.verification_request)
                self.assertEqual(target.read_text(encoding="utf-8"), "original")
            finally:
                app.destroy()

    def test_deny_cancel_reset_and_stale_events_never_start_or_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, request = self.prepare_request(app, root, "deny-verification")
                with mock.patch.object(app, "_start_verification_worker") as runner:
                    self.assertTrue(app.deny_verification())
                runner.assert_not_called()
                self.assertIsNone(app.verification_request)
                self.assertFalse(app.lifecycle.accepts(snapshot.run_id))

                snapshot, request = self.prepare_request(app, root, "reset-verification")
                app.reset_session()
                self.assertIsNone(app.verification_request)
                app.work_queue.put(wrapper.RunEvent(snapshot.run_id, "verification_request", request, 1))
                app._poll_queue()
                self.assertIsNone(app.verification_request)
                self.assertFalse(app.cancel_verification_request())
            finally:
                app.destroy()

    def test_folder_change_and_close_clear_pending_permission(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as next_dir:
            root = Path(temp_dir)
            next_root = Path(next_dir)
            app = self.make_app(root)
            try:
                self.prepare_request(app, root, "folder-verification")
                app.task_state = wrapper.TASK_STATE_REVIEW
                with (
                    mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(next_root)),
                    mock.patch.object(wrapper, "save_local_config"),
                    mock.patch.object(app, "scan_folder", return_value=True),
                ):
                    app.choose_folder()
                self.assertIsNone(app.verification_request)
                self.assertIsNone(app.run_snapshot)
            finally:
                app.destroy()

            app = self.make_app(root)
            self.prepare_request(app, root, "close-verification")
            app.on_close()
            self.assertTrue(app.lifecycle.closed)
            self.assertIsNone(app.verification_request)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class VerificationContinuationUiTests(unittest.TestCase):
    class FakeProcess:
        def __init__(self, output=b"verification ok"):
            self.stdout = None
            self.returncode = 0
            self.output = output
            self.terminated = 0
            self.killed = 0

        def communicate(self, timeout=None):
            return self.output, b""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated += 1
            self.returncode = 0

        def kill(self):
            self.killed += 1
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    def make_app(self, root):
        return wrapper.CodeAgentApp(history_path=root / "history.json")

    def prepare_continuation(self, app, root, run_id="verification-continuation"):
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="continue after verification",
            verification_round=1,
        )
        app.selected_folder.set(str(root))
        app.lifecycle.activate(snapshot)
        app.run_resources.create(snapshot.run_id)
        app.run_snapshot = snapshot
        app._handoff_snapshot = snapshot
        app._handoff_stale = False
        app._handoff_evidence_events = []
        app.task_state = wrapper.TASK_STATE_RUNNING
        verification_run_id = f"verification-{run_id}"
        app.verification_run_id = verification_run_id
        app._verification_command_root = root
        app._verification_executor_run_id = run_id
        app._verification_continuation_started = False
        app.verification_command.set("python -m pytest tests")
        app._verification_lineage = wrapper.VerificationLineage(
            parent_executor_run_id=run_id,
            child_verification_run_id=verification_run_id,
            command_identity=wrapper.verification_command_identity(("python", "-m", "pytest", "tests")),
        )
        app._reset_run_timeline(run_id)
        app.run_resources.create(verification_run_id)
        return snapshot, verification_run_id

    @staticmethod
    def drain(app):
        events = []
        while True:
            try:
                events.append(app.work_queue.get_nowait())
            except queue.Empty:
                return events

    def test_mock_popen_emits_one_bounded_result_and_cleans_runner_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, verification_run_id = self.prepare_continuation(app, root, "popen-result")
                raw_output = b"ok\nAuthorization: Bearer raw-token\npassword=raw-secret"
                fake_process = self.FakeProcess(raw_output)
                with mock.patch.object(wrapper.subprocess, "Popen", return_value=fake_process) as popen:
                    app._run_verification_worker(
                        verification_run_id,
                        ("python", "-m", "pytest", "tests"),
                        root,
                        snapshot.run_id,
                    )
                popen.assert_called_once()
                self.assertFalse(popen.call_args.kwargs["shell"])
                self.assertEqual(Path(popen.call_args.kwargs["cwd"]).resolve(), root.resolve())
                result_events = [event for event in self.drain(app) if event[1] == "verification_complete"]
                self.assertEqual(len(result_events), 1)
                result = result_events[0][2]
                self.assertIsInstance(result, wrapper.VerificationResult)
                self.assertEqual(result.status, "exit")
                self.assertNotIn("raw-token", result.output)
                self.assertNotIn("raw-secret", result.output)
                self.assertIsNone(app.run_resources.get(verification_run_id))
            finally:
                app.destroy()

    def test_terminal_result_starts_exactly_one_continuation_and_never_proposes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, _ = self.prepare_continuation(app, root, "one-continuation")
                result = wrapper.VerificationResult(
                    "verification-one-continuation",
                    snapshot.run_id,
                    "python -m pytest tests",
                    "exit",
                    0,
                    "ok\nraw-token",
                )
                with mock.patch.object(app, "_start_run_worker", return_value=object()) as next_worker:
                    self.assertTrue(app._handle_verification_complete(result))
                    self.assertFalse(app._handle_verification_complete(result))
                next_worker.assert_called_once()
                continuation_args = next_worker.call_args.args[2]
                self.assertIs(continuation_args[4], result)
                self.assertFalse(app.pending_proposal)
                self.assertNotIn("raw-token", app.activity.get("1.0", "end"))
            finally:
                app._stop_verification(keep_identity=False)
                app.destroy()

    def test_child_events_stay_on_parent_timeline_and_handoff_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, verification_run_id = self.prepare_continuation(app, root, "lineage-parent")
                app._record_timeline_event(snapshot.run_id, 1, "timeline", "parent executor event")
                result = wrapper.VerificationResult(
                    verification_run_id,
                    snapshot.run_id,
                    "python -m pytest tests",
                    "exit",
                    0,
                    "Authorization: Bearer raw-token",
                )
                child_events = (
                    wrapper.RunEvent(verification_run_id, "verification_start", "Started: python -m pytest tests", 1),
                    wrapper.RunEvent(verification_run_id, "verification_complete", result, 2),
                    wrapper.RunEvent(verification_run_id, "verification_exit", "Verification exited with code 0.", 3),
                )
                with mock.patch.object(app, "_start_run_worker", return_value=object()) as next_worker:
                    for event in child_events:
                        app.work_queue.put(event)
                    app._poll_queue()
                next_worker.assert_called_once()
                self.assertIsNone(app.verification_run_id)
                self.assertEqual(app._verification_lineage.parent_executor_run_id, snapshot.run_id)
                self.assertEqual(app._verification_lineage.child_verification_run_id, verification_run_id)
                timeline = app.run_timeline
                self.assertTrue(all(item["run_id"] == snapshot.run_id for item in timeline))
                child_timeline = [item for item in timeline if item.get("source_run_id") == verification_run_id]
                self.assertEqual([item["source_sequence"] for item in child_timeline], [1, 2, 3])
                self.assertEqual([item["sequence"] for item in timeline], sorted(item["sequence"] for item in timeline))
                handoff = app._build_current_handoff()
                handoff_text = "\n".join(handoff.verification_statuses)
                self.assertIn(snapshot.run_id, handoff_text)
                self.assertIn(verification_run_id, handoff_text)
                self.assertIn("output_present=True", handoff_text)
                self.assertIn("output_bytes=", handoff_text)
                self.assertNotIn("raw-token", handoff_text)
                self.assertNotIn("Authorization", app.activity.get("1.0", "end"))
            finally:
                app._stop_verification(keep_identity=False)
                app.destroy()

    def test_cross_run_result_is_rejected_without_parent_continuation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, verification_run_id = self.prepare_continuation(app, root, "lineage-cross-run")
                wrong_result = wrapper.VerificationResult(
                    "verification-other-child",
                    snapshot.run_id,
                    "python -m pytest tests",
                    "exit",
                    0,
                    "safe",
                )
                with mock.patch.object(app, "_start_run_worker") as next_worker:
                    self.assertFalse(app._handle_verification_complete(wrong_result))
                next_worker.assert_not_called()
                self.assertTrue(app.lifecycle.accepts(snapshot.run_id))
                self.assertEqual(app.verification_run_id, verification_run_id)
                self.assertIsNone(app.pending_proposal)
            finally:
                app._stop_verification(keep_identity=False)
                app.destroy()

    def test_result_output_is_not_history_or_handoff_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, _ = self.prepare_continuation(app, root, "metadata-only")
                result = wrapper.VerificationResult(
                    "verification-metadata-only",
                    snapshot.run_id,
                    "python -m pytest tests",
                    "exit",
                    0,
                    "Authorization: Bearer raw-token\n" + ("x" * 100000),
                )
                app._record_timeline_event(
                    "verification-metadata-only",
                    1,
                    "verification_complete",
                    result,
                )
                timeline_text = "\n".join(item["text"] for item in app.run_timeline)
                self.assertNotIn("raw-token", timeline_text)
                self.assertNotIn("raw-token", app.activity.get("1.0", "end"))
                self.assertEqual(app._handoff_evidence_events, [])
                history_path = root / "history.json"
                self.assertFalse(history_path.exists())
            finally:
                app._stop_verification(keep_identity=False)
                app.destroy()

    def test_close_clears_parent_child_lineage_without_continuation_or_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "sentinel.txt"
            target.write_text("original", encoding="utf-8")
            app = self.make_app(root)
            self.prepare_continuation(app, root, "lineage-close")
            with mock.patch.object(app, "_start_run_worker") as next_worker:
                app.on_close()
            next_worker.assert_not_called()
            self.assertTrue(app.lifecycle.closed)
            self.assertIsNone(app._verification_lineage)
            self.assertIsNone(app.pending_proposal)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_cancel_reset_folder_close_and_stale_result_do_not_continue_or_write(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as next_dir:
            root = Path(temp_dir)
            target = root / "sentinel.txt"
            target.write_text("original", encoding="utf-8")
            app = self.make_app(root)
            try:
                snapshot, _ = self.prepare_continuation(app, root, "cancel-continuation")
                result = wrapper.VerificationResult("verification-cancel-continuation", snapshot.run_id, "python -m pytest tests", "exit", 0, "ok")
                with mock.patch.object(app, "_start_run_worker") as next_worker:
                    self.assertTrue(app.cancel_verification())
                next_worker.assert_not_called()
                self.assertFalse(app.lifecycle.accepts(snapshot.run_id))
                self.assertIsNone(app.pending_proposal)
                self.assertEqual(target.read_text(encoding="utf-8"), "original")

                snapshot, verification_run_id = self.prepare_continuation(app, root, "reset-continuation")
                with mock.patch.object(app, "_start_run_worker") as next_worker:
                    app.reset_session()
                next_worker.assert_not_called()
                self.assertIsNone(app.lifecycle.active_run_id)
                self.assertIsNone(app._verification_executor_run_id)

                snapshot, verification_run_id = self.prepare_continuation(app, root, "folder-continuation")
                app.task_state = wrapper.TASK_STATE_REVIEW
                with (
                    mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(next_dir)),
                    mock.patch.object(wrapper, "save_local_config"),
                    mock.patch.object(app, "scan_folder", return_value=True),
                ):
                    app.choose_folder()
                self.assertIsNone(app.lifecycle.active_run_id)
                self.assertIsNone(app._verification_executor_run_id)

                snapshot, verification_run_id = self.prepare_continuation(app, root, "stale-continuation")
                app.lifecycle.invalidate()
                app.work_queue.put(
                    wrapper.RunEvent(
                        verification_run_id,
                        "verification_complete",
                        wrapper.VerificationResult(
                            verification_run_id,
                            snapshot.run_id,
                            "python -m pytest tests",
                            "exit",
                            0,
                            "stale raw-token",
                        ),
                        1,
                    )
                )
                with mock.patch.object(app, "_start_run_worker") as next_worker:
                    app._poll_queue()
                next_worker.assert_not_called()
                self.assertNotIn("stale raw-token", app.activity.get("1.0", "end"))
            finally:
                if not app.lifecycle.closed:
                    app.on_close()

    def test_timeout_emits_metadata_only_result_and_cleans_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, verification_run_id = self.prepare_continuation(app, root, "timeout-continuation")
                fake_process = self.FakeProcess(b"partial raw-token")
                with (
                    mock.patch.object(wrapper.subprocess, "Popen", return_value=fake_process),
                    mock.patch.object(wrapper, "VERIFICATION_TIMEOUT_SECONDS", 0),
                ):
                    app._run_verification_worker(
                        verification_run_id,
                        ("python", "-m", "pytest", "tests"),
                        root,
                        snapshot.run_id,
                    )
                result_events = [event for event in self.drain(app) if event[1] == "verification_complete"]
                self.assertEqual(len(result_events), 1)
                self.assertEqual(result_events[0][2].status, "timeout")
                self.assertNotIn("raw-token", result_events[0][2].output)
                self.assertIsNone(app.run_resources.get(verification_run_id))
                self.assertFalse(app.pending_proposal)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
