import queue
import subprocess
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class FakeStream:
    def __init__(self, chunks, on_read=None, process=None):
        self.chunks = list(chunks)
        self.on_read = on_read
        self.process = process

    def read1(self, _size):
        if self.on_read is not None:
            callback = self.on_read
            self.on_read = None
            callback()
        if self.chunks:
            return self.chunks.pop(0)
        if (
            self.process is not None
            and self.process.returncode is None
            and self.process.exit_on_eof
        ):
            self.process.returncode = 0
        return b""


class GroupProcess:
    def __init__(self, chunks, on_read=None, exit_on_eof=True):
        self.returncode = None
        self.exit_on_eof = exit_on_eof
        self.poll_calls = 0
        self.stdout = FakeStream(chunks, on_read=on_read, process=self)
        self.terminate_group_calls = 0
        self.kill_group_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        self.poll_calls += 1
        if not self.exit_on_eof and self.poll_calls >= 2:
            self.returncode = 0
        return self.returncode

    def terminate_group(self):
        self.terminate_group_calls += 1
        self.returncode = -15

    def kill_group(self):
        self.kill_group_calls += 1
        self.returncode = -9

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9


class StreamHost:
    def __init__(self, root):
        self.api_key = "policy-api-key-123456"
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


def run_stream_worker(host, process, root, run_id="policy-run"):
    host.verification_run_id = run_id
    owner = host.run_resources.create(run_id)
    host.run_resources.register_worker(run_id, threading.current_thread())
    with mock.patch.object(wrapper.subprocess, "Popen", return_value=process) as popen:
        wrapper.CodeAgentApp._run_verification_worker(host, run_id, ("python", "-c", "pass"), root)
    return owner, popen


class EnvironmentPolicyTests(unittest.TestCase):
    def test_sanitized_environment_excludes_secret_shaped_values_and_is_bounded(self):
        source = {
            "PATH": "C:\\safe\\bin",
            "PATHEXT": ".EXE;.BAT",
            "TEMP": "Bearer raw-bearer-value",
            "LANG": "en_US",
            "OPENROUTER_API_KEY": "raw-openrouter-key-123456",
            "SERVICE_TOKEN": "raw-token-123456",
            "AUTHORIZATION": "Bearer raw-auth-123456",
            "SAFE_BUT_HUGE": "x" * 10000,
        }
        safe = wrapper.build_verification_environment(source)
        self.assertEqual(safe["PATH"], source["PATH"])
        self.assertEqual(safe["PATHEXT"], source["PATHEXT"])
        self.assertNotIn("TEMP", safe)
        self.assertNotIn("OPENROUTER_API_KEY", safe)
        self.assertNotIn("SERVICE_TOKEN", safe)
        self.assertNotIn("AUTHORIZATION", safe)
        self.assertNotIn("raw-openrouter-key-123456", repr(safe))
        self.assertLessEqual(len(safe), wrapper.VERIFICATION_ENV_MAX_ITEMS)
        self.assertLessEqual(
            sum(len(key) + len(value) for key, value in safe.items()),
            wrapper.VERIFICATION_ENV_MAX_TOTAL_CHARS,
        )

    def test_popen_receives_sanitized_environment_without_logging_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            process = GroupProcess([b"ok\n"])
            host = StreamHost(root)
            raw_key = host.api_key
            with mock.patch.dict(
                wrapper.os.environ,
                {
                    "OPENROUTER_API_KEY": raw_key,
                    "SERVICE_TOKEN": "secret-token-123456",
                    "PATH": "C:\\safe\\bin",
                },
                clear=False,
            ):
                owner, popen = run_stream_worker(host, process, root)
            child_env = popen.call_args.kwargs["env"]
            self.assertNotIn("OPENROUTER_API_KEY", child_env)
            self.assertNotIn("SERVICE_TOKEN", child_env)
            self.assertNotIn(raw_key, repr(child_env))
            self.assertEqual(owner.process_handles, ())


class ExecutablePolicyTests(unittest.TestCase):
    def test_preset_is_allowed_unknown_is_distinct_and_shell_wrappers_are_blocked(self):
        for executable in ("python", "py", "node", "npm", "pnpm", "pytest", "cargo", "dotnet", "git"):
            argv = wrapper.parse_verification_command(f"{executable} --version")
            self.assertEqual(wrapper.verification_command_policy(argv), "allowed")
        unknown = wrapper.parse_verification_command("ruby --version")
        self.assertEqual(wrapper.verification_command_policy(unknown), "unknown")
        for blocked in ("cmd.exe /c whoami", "powershell -Command whoami", "bash -c whoami", "npm.cmd --version"):
            with self.subTest(blocked=blocked):
                with self.assertRaises(ValueError):
                    wrapper.parse_verification_command(blocked)


class IncrementalStreamTests(unittest.TestCase):
    def test_eof_waits_for_process_exit_without_losing_terminal_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            process = GroupProcess([b"done\n"], exit_on_eof=False)
            host = StreamHost(root)
            with mock.patch.object(wrapper, "VERIFICATION_TIMEOUT_SECONDS", 1):
                owner, _ = run_stream_worker(host, process, root, "eof-before-exit")
            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())
            self.assertEqual(events[-1].kind, "verification_exit")
            self.assertEqual(owner.process_handles, ())

    def test_chunks_are_redacted_incrementally_and_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_key = "policy-api-key-123456"
            process = GroupProcess(
                [
                    f"first {raw_key}\n".encode("utf-8"),
                    b"1234567890",
                ]
            )
            host = StreamHost(root)
            with mock.patch.object(wrapper, "VERIFICATION_MAX_OUTPUT_BYTES", 10):
                owner, popen = run_stream_worker(host, process, root, "incremental-limit")
            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())
            output = b"".join(
                event.payload.encode("utf-8")
                for event in events
                if event.kind == "verification_output"
            )
            self.assertLessEqual(len(output), 10)
            self.assertNotIn(raw_key, "\n".join(event.payload for event in events))
            self.assertEqual(events[-1].kind, "verification_error")
            self.assertFalse(any(event.kind == "verification_exit" for event in events))
            self.assertGreaterEqual(process.terminate_group_calls, 1)
            self.assertEqual(owner.process_handles, ())
            self.assertEqual(owner.worker_handles, ())
            self.assertIn("env", popen.call_args.kwargs)


class ProcessContainmentTests(unittest.TestCase):
    def test_group_termination_is_requested_and_all_handles_are_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            owner_holder = {}

            def cancel_on_read():
                owner_holder["owner"].cancel()

            process = GroupProcess([b"late\n"], on_read=cancel_on_read)
            host = StreamHost(root)
            host.verification_run_id = "cancel-tree"
            owner = host.run_resources.create("cancel-tree")
            owner_holder["owner"] = owner
            host.run_resources.register_worker("cancel-tree", threading.current_thread())
            with mock.patch.object(wrapper.subprocess, "Popen", return_value=process):
                wrapper.CodeAgentApp._run_verification_worker(host, "cancel-tree", ("python",), root)
            self.assertGreaterEqual(process.terminate_group_calls, 1)
            self.assertEqual(owner.process_handles, ())
            self.assertEqual(owner.worker_handles, ())


class ConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")

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

    def test_unknown_executable_requires_distinct_policy_and_run_confirmation(self):
        self.app.verification_command.set("ruby --version")
        with mock.patch.object(wrapper.messagebox, "askyesno", side_effect=[True, False]) as confirm, mock.patch.object(
            self.app, "_start_verification_worker", return_value=True
        ) as start:
            self.assertFalse(self.app.run_verification())
            self.assertEqual(confirm.call_count, 2)
            start.assert_not_called()

    def test_allowed_executable_still_requires_user_run_confirmation(self):
        self.app.verification_command.set("python --version")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=False) as confirm, mock.patch.object(
            self.app, "_start_verification_worker", return_value=True
        ) as start:
            self.assertFalse(self.app.run_verification())
            confirm.assert_called_once()
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
