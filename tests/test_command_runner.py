import queue
import os
import subprocess
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class FakeProcess:
    def __init__(self, output=b"", returncode=0, timeout=False, on_communicate=None):
        self.output = output
        self.returncode = None if timeout else returncode
        self.final_returncode = returncode
        self.timeout = timeout
        self.on_communicate = on_communicate
        self.communicate_calls = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout=None):
        self.communicate_calls.append(timeout)
        if self.on_communicate is not None:
            callback = self.on_communicate
            self.on_communicate = None
            callback(self)
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["fake"], timeout, output=b"partial\n")
        return self.output, None

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9


class VerificationHost:
    def __init__(self, root):
        self.api_key = "runner-api-key-123456"
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()
        self.run_resources = wrapper.RunResourceRegistry()
        self.verification_run_id = None
        self._verification_command_root = root

    def _verification_is_active(self, run_id=None):
        target = run_id if run_id is not None else self.verification_run_id
        return bool(target) and not self.lifecycle.closed and target == self.verification_run_id

    def _verification_work_is_current(self, run_id):
        return self._verification_is_active(run_id) and self.run_resources.is_current(run_id)

    def _finish_run_worker(self, run_id):
        self.run_resources.unregister_worker(run_id, threading.current_thread())


def run_worker(host, process, root, run_id="verification-test"):
    host.verification_run_id = run_id
    owner = host.run_resources.create(run_id)
    host.run_resources.register_worker(run_id, threading.current_thread())
    with mock.patch.object(wrapper.subprocess, "Popen", return_value=process) as popen:
        wrapper.CodeAgentApp._run_verification_worker(host, run_id, ("python", "-m", "unittest"), root)
    return owner, popen


class VerificationParsingTests(unittest.TestCase):
    def test_valid_command_uses_argv_and_rejects_shell_input(self):
        self.assertEqual(
            wrapper.parse_verification_command("python -m py_compile codex_free_wrapper.py"),
            ("python", "-m", "py_compile", "codex_free_wrapper.py"),
        )
        for invalid in ("", "   ", "python; whoami", "python && whoami", "python > output", "python\nnext", "powershell -Command x"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    wrapper.parse_verification_command(invalid)

    def test_root_must_exist_and_cwd_must_equal_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(wrapper.validate_verification_root(root, cwd=root), root.resolve())
            with self.assertRaises(ValueError):
                wrapper.validate_verification_root(root, cwd=root.parent)
            with self.assertRaises(ValueError):
                wrapper.validate_verification_root(root / "missing")
            with self.assertRaises(ValueError):
                wrapper.validate_verification_root(root / "file.txt")
            (root / "file.txt").write_text("not a root", encoding="utf-8")
            with self.assertRaises(ValueError):
                wrapper.validate_verification_root(root / "file.txt")


class VerificationWorkerTests(unittest.TestCase):
    def test_worker_uses_shell_false_exact_root_and_redacted_sequenced_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_key = "runner-api-key-123456"
            raw_bearer = "runner-bearer-123456"
            process = FakeProcess(
                output=(f"ok {raw_key}\nAuthorization: Bearer {raw_bearer}\n").encode("utf-8"),
                returncode=0,
            )
            host = VerificationHost(root)
            owner, popen = run_worker(host, process, root)

            args, kwargs = popen.call_args
            self.assertEqual(args[0], ["python", "-m", "unittest"])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["cwd"], str(root.resolve()))
            self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())
            self.assertEqual([event.kind for event in events], ["verification_start", "verification_output", "verification_exit"])
            self.assertEqual([event.sequence for event in events], [1, 2, 3])
            self.assertFalse(
                any(event.kind in {"proposal", "diffs", "files", "auto_apply", "history"} for event in events)
            )
            joined = "\n".join(event.payload for event in events)
            self.assertNotIn(raw_key, joined)
            self.assertNotIn(raw_bearer, joined)
            self.assertEqual(owner.process_handles, ())
            self.assertEqual(owner.worker_handles, ())

    def test_output_limit_and_timeout_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            process = FakeProcess(output=b"123456789", returncode=0)
            host = VerificationHost(root)
            with mock.patch.object(wrapper, "VERIFICATION_MAX_OUTPUT_BYTES", 4):
                owner, _ = run_worker(host, process, root, "output-limit")
            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())
            self.assertEqual(events[-1].kind, "verification_error")
            output_events = [event for event in events if event.kind == "verification_output"]
            self.assertEqual(len(output_events[0].payload), 4)
            self.assertEqual(owner.process_handles, ())

            timeout_process = FakeProcess(timeout=True)
            timeout_host = VerificationHost(root)
            with mock.patch.object(wrapper, "VERIFICATION_TIMEOUT_SECONDS", 0):
                timeout_owner, _ = run_worker(timeout_host, timeout_process, root, "timeout")
            timeout_events = []
            while not timeout_host.work_queue.empty():
                timeout_events.append(timeout_host.work_queue.get_nowait())
            self.assertEqual(timeout_events[-1].kind, "verification_timeout")
            self.assertGreaterEqual(timeout_process.terminate_calls, 1)
            self.assertEqual(timeout_owner.process_handles, ())

    def test_cancellation_stops_process_and_emits_no_exit_or_late_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            host = VerificationHost(root)
            run_id = "cancel"
            host.verification_run_id = run_id
            owner = host.run_resources.create(run_id)
            owner_holder = {"owner": owner}
            host.run_resources.register_worker(run_id, threading.current_thread())

            def cancel_on_communicate(_process):
                owner_holder["owner"].cancel()

            process = FakeProcess(timeout=True, on_communicate=cancel_on_communicate)
            with mock.patch.object(wrapper.subprocess, "Popen", return_value=process):
                wrapper.CodeAgentApp._run_verification_worker(host, run_id, ("python",), root)
            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())
            self.assertGreaterEqual(process.terminate_calls, 1)
            self.assertFalse(any(event.kind == "verification_exit" for event in events))
            self.assertFalse(any(event.kind == "verification_output" and event.payload == "late" for event in events))
            self.assertEqual(owner.process_handles, ())

    def test_stale_events_are_rejected_after_reset_identity_invalidation(self):
        events = queue.Queue()
        run_id = "stale-verification"
        active = {"value": True}
        self.assertTrue(
            wrapper.queue_run_event(
                events,
                run_id,
                "verification_output",
                "before",
                is_current=lambda: active["value"],
            )
        )
        active["value"] = False
        self.assertFalse(
            wrapper.queue_run_event(
                events,
                run_id,
                "verification_output",
                "after",
                is_current=lambda: active["value"],
            )
        )
        event = events.get_nowait()
        self.assertTrue(wrapper.event_matches_run(event, run_id))
        self.assertEqual(event.sequence, 1)
        self.assertTrue(events.empty())

    def test_owner_cancel_requests_process_termination_without_waiting_and_cleans_handle(self):
        registry = wrapper.RunResourceRegistry()
        owner = registry.create("owned-process")
        process = FakeProcess(timeout=True)
        self.assertTrue(registry.register_process("owned-process", process))
        owner.cancel()
        self.assertEqual(process.terminate_calls, 1)
        registry.unregister_process("owned-process", process)
        self.assertEqual(owner.process_handles, ())


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ExplicitUiActionTests(unittest.TestCase):
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
        self.app = wrapper.CodeAgentApp(history_path=Path(self.temp_dir.name) / "history.json")
        self.app.withdraw()
        self.app.selected_folder.set(str(self.root))

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def attach_process(self, run_id):
        owner = self.app.run_resources.create(run_id)
        process = FakeProcess(timeout=True)
        self.assertTrue(owner.register_process(process))
        self.app.verification_run_id = run_id
        return owner, process

    def test_command_is_not_started_by_model_plan_or_startup_paths(self):
        self.app.verification_command.set("python -m unittest")
        with mock.patch.object(wrapper.subprocess, "Popen") as popen, mock.patch.object(
            wrapper.messagebox, "askyesno", return_value=False
        ) as confirm:
            self.app._poll_queue()
            self.assertFalse(popen.called)
            self.assertFalse(confirm.called)
            self.assertFalse(self.app.run_verification())
            confirm.assert_called_once()
            popen.assert_not_called()

    def test_confirmed_button_action_is_the_only_start_path(self):
        self.app.verification_command.set("python -m unittest")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True) as confirm, mock.patch.object(
            self.app, "_start_verification_worker", return_value=True
        ) as start:
            self.assertTrue(self.app.run_verification())
            confirm.assert_called_once()
            start.assert_called_once_with(("python", "-m", "unittest"), self.root.resolve())

    def test_reset_folder_explicit_cancel_and_close_terminate_owned_process(self):
        owner, process = self.attach_process("reset-process")
        self.app.reset_session()
        self.assertEqual(process.terminate_calls, 1)
        self.assertIsNone(self.app.verification_run_id)
        self.assertEqual(owner.process_handles, (process,))
        owner.unregister_process(process)

        owner, process = self.attach_process("folder-process")
        new_root = Path(self.temp_dir.name) / "new-project"
        new_root.mkdir()
        with mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(new_root)):
            self.app.choose_folder()
        self.assertEqual(process.terminate_calls, 1)
        owner.unregister_process(process)

        owner, process = self.attach_process("cancel-process")
        self.assertTrue(self.app.cancel_verification())
        self.assertEqual(process.terminate_calls, 1)
        owner.unregister_process(process)

        owner, process = self.attach_process("close-process")
        self.app.on_close()
        self.assertEqual(process.terminate_calls, 1)
        owner.unregister_process(process)

    def test_verification_events_never_enter_history(self):
        self.app.verification_run_id = "history-boundary"
        self.app.run_resources.create("history-boundary")
        self.app.work_queue.put(wrapper.RunEvent("history-boundary", "verification_output", "file contents", 1))
        self.app._poll_queue()
        history_text = (Path(self.temp_dir.name) / "history.json").read_text(encoding="utf-8") if (Path(self.temp_dir.name) / "history.json").exists() else ""
        self.assertNotIn("file contents", history_text)
        self.assertIn("file contents", self.app.activity.get("1.0", tk.END))


if __name__ == "__main__":
    unittest.main()
