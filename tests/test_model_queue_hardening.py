import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class LifecycleWorkerHost:
    def __init__(self, api_key="worker-api-key-123456"):
        self.api_key = api_key
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()

    def _run_is_current(self, run_id):
        return self.lifecycle.accepts(run_id)


class ModelQueueHardeningTests(unittest.TestCase):
    def drain(self, work_queue):
        events = []
        while not work_queue.empty():
            events.append(work_queue.get_nowait())
        return events

    def test_zero_priced_non_suffix_model_is_preserved_and_paid_model_is_rejected(self):
        payload = {
            "data": [
                {"id": "zero/plain", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "paid/model", "pricing": {"prompt": "0.000001", "completion": "0"}},
                {"id": "tagged:free", "pricing": {"prompt": "0.1", "completion": "0"}},
                {"id": "known:free"},
            ]
        }
        with mock.patch.object(wrapper, "urlopen", return_value=FakeResponse(payload)):
            discovered = wrapper.discover_free_models("discovery-key")

        self.assertEqual(list(discovered), ["known:free", "zero/plain"])
        ordered = wrapper.order_free_model_queue(discovered, static_models=[])
        self.assertEqual(list(ordered), ["known:free", "zero/plain"])
        self.assertEqual(wrapper._filter_free_model_queue(["paid/model"]), [])

        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter", return_value='{"summary":"ok","files":[]}') as provider:
            result, model = wrapper.call_openrouter_with_fallback(
                api_key="discovery-key",
                instructions="safe",
                files=[],
                session_messages=[],
                log_queue=events,
                run_id="free-run",
                model_queue=[
                    {"id": "zero/plain", "pricing": {"prompt": "0", "completion": "0"}},
                    {"id": "paid/model", "pricing": {"prompt": "0.000001", "completion": "0"}},
                ],
            )

        self.assertEqual(model, "zero/plain")
        self.assertEqual(result["files"], [])
        self.assertEqual(provider.call_args.args[1], "zero/plain")
        self.assertNotIn("paid/model", [call.args[1] for call in provider.call_args_list])

    def test_ordering_and_discovery_failure_keep_deterministic_static_fallback(self):
        discovered = wrapper.FreeModelDiscoveryResult(
            [
                {"id": "zeta:free"},
                {"id": "zero/plain", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "alpha:free"},
            ]
        )
        ordered = wrapper.order_free_model_queue(discovered, static_models=["known:free", "alpha:free"])
        self.assertEqual(list(ordered), ["alpha:free", "zero/plain", "zeta:free", "known:free"])

        fallback, note = wrapper.build_free_model_queue(
            "discovery-key",
            discovery_fn=mock.Mock(side_effect=TimeoutError("bounded timeout")),
            static_models=["zeta:free", "alpha:free", "paid/model"],
        )
        self.assertEqual(list(fallback), ["zeta:free", "alpha:free"])
        self.assertIn("discovery failed", note.lower())

    def test_cancellation_after_first_failure_prevents_second_candidate_and_event(self):
        events = queue.Queue()
        active = {"value": True}

        def fail_first(*_args):
            active["value"] = False
            raise RuntimeError("transient provider failure")

        with mock.patch.object(wrapper, "call_openrouter", side_effect=fail_first) as provider:
            with self.assertRaises(wrapper.RunCancelledError):
                wrapper.call_openrouter_with_fallback(
                    api_key="safe-key",
                    instructions="safe",
                    files=[],
                    session_messages=[],
                    log_queue=events,
                    run_id="cancel-after-failure",
                    event_is_current=lambda: active["value"],
                    model_queue=["first:free", "second:free"],
                )

        self.assertEqual(provider.call_count, 1)
        queued = self.drain(events)
        self.assertEqual([event[1] for event in queued], ["model_status"])
        self.assertNotIn("second:free", str(queued))

    def test_cancellation_after_provider_return_prevents_proposal_and_apply(self):
        host = LifecycleWorkerHost()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="cancel-after-return",
            )
            host.lifecycle.activate(snapshot)

            def return_then_cancel(**_kwargs):
                host.lifecycle.invalidate()
                return (
                    {"summary": "should not become a proposal", "files": [{"path": "note.txt", "content": "after"}]},
                    "first:free",
                )

            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=(["first:free"], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", side_effect=return_then_cancel),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe instruction")

            events = self.drain(host.work_queue)

        self.assertFalse((root / "note.txt").exists())
        self.assertFalse(any(event[1] in {"proposal", "auto_apply"} for event in events))
        self.assertNotIn(wrapper.TASK_STATE_REVIEW, [event[2][0] for event in events if event[1] == "task_state"])

    def test_provider_and_worker_errors_are_redacted_before_queue(self):
        raw_api_key = "raw-api-key-123456789"
        raw_bearer = "raw-bearer-token-123456789"
        provider_error = RuntimeError(
            f"api_key={raw_api_key}; Authorization: Bearer {raw_bearer}"
        )

        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter", side_effect=provider_error):
            with self.assertRaises(RuntimeError) as raised:
                wrapper.call_openrouter_with_fallback(
                    api_key=raw_api_key,
                    instructions="safe",
                    files=[],
                    session_messages=[],
                    log_queue=events,
                    run_id="redaction-run",
                    model_queue=["one:free"],
                )
        self.assertNotIn(raw_api_key, str(raised.exception))
        queued = self.drain(events)
        queued_text = str(queued)
        self.assertNotIn(raw_api_key, queued_text)
        self.assertNotIn(raw_bearer, queued_text)
        self.assertIn("[redacted]", queued_text)

        host = LifecycleWorkerHost(api_key=raw_api_key)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="worker-redaction-run",
            )
            host.lifecycle.activate(snapshot)
            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(
                    wrapper,
                    "build_free_model_queue",
                    side_effect=RuntimeError(
                        f"api_key={raw_api_key}; Authorization: Bearer {raw_bearer}"
                    ),
                ),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe instruction")

        worker_text = str(self.drain(host.work_queue))
        self.assertNotIn(raw_api_key, worker_text)
        self.assertNotIn(raw_bearer, worker_text)
        self.assertIn("[redacted]", worker_text)


if __name__ == "__main__":
    unittest.main()
