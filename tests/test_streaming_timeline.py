import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


class ChunkedResponse:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return next(self.chunks, b"")


def sse_event(content):
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def streamed_response(content_parts, split_at=None):
    body = b"".join(sse_event(part) for part in content_parts) + b"data: [DONE]\n\n"
    if split_at is None:
        return ChunkedResponse([body])
    return ChunkedResponse([body[:split_at], body[split_at:]])


class WorkerHost:
    def __init__(self, api_key="stream-api-key-123456"):
        self.api_key = api_key
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()

    def _run_is_current(self, run_id):
        return self.lifecycle.accepts(run_id)


class StreamingTimelineTests(unittest.TestCase):
    def drain(self, work_queue):
        events = []
        while not work_queue.empty():
            events.append(work_queue.get_nowait())
        return events

    def make_snapshot(self, root, run_id="stream-run"):
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
        )
        return snapshot

    def test_valid_sse_chunks_request_stream_and_assemble_before_parse(self):
        raw_key = "raw-stream-api-key-123456"
        response_text = '{"summary":"done","files":[]}'
        response = streamed_response(
            [response_text[:12], response_text[12:]],
            split_at=9,
        )
        events = queue.Queue()
        with mock.patch.object(wrapper, "urlopen", return_value=response) as opener:
            assembled = wrapper.call_openrouter(
                raw_key,
                "coding:free",
                "safe instruction",
                [],
                [],
                log_queue=events,
                run_id="stream-run",
                event_is_current=lambda: True,
            )

        self.assertEqual(assembled, response_text)
        self.assertEqual(wrapper.parse_model_response(assembled)["summary"], "done")
        request = opener.call_args.args[0]
        self.assertTrue(json.loads(request.data)["stream"])
        queued = self.drain(events)
        self.assertTrue(all(event.run_id == "stream-run" for event in queued))
        self.assertEqual([event.sequence for event in queued], list(range(1, len(queued) + 1)))
        self.assertEqual("".join(event.payload for event in queued), response_text)
        self.assertNotIn(raw_key, str(queued))

    def test_malformed_and_empty_streams_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Malformed"):
            wrapper.assemble_openrouter_stream(
                ChunkedResponse([b"data: {not-json}\n\n"]),
            )
        with self.assertRaisesRegex(ValueError, "no text"):
            wrapper.assemble_openrouter_stream(
                ChunkedResponse([b"data: [DONE]\n\n"]),
            )

    def test_cancellation_after_a_chunk_stops_before_next_chunk(self):
        active = {"value": True}
        emitted = []
        response = streamed_response(["first", "second"])

        def emit_chunk(text):
            emitted.append(text)
            active["value"] = False
            return True

        with self.assertRaises(wrapper.RunCancelledError):
            wrapper.assemble_openrouter_stream(
                response,
                is_current=lambda: active["value"],
                emit_chunk=emit_chunk,
            )
        self.assertEqual(emitted, ["first"])

    def test_stale_run_events_are_rejected_and_sequence_is_monotonic(self):
        lifecycle = wrapper.RunLifecycle()
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = self.make_snapshot(Path(temp_dir), run_id="timeline-run")
            lifecycle.activate(snapshot)
            events = queue.Queue()
            is_current = lambda: lifecycle.accepts(snapshot.run_id)
            self.assertTrue(wrapper.queue_run_event(events, snapshot.run_id, "timeline", "one", is_current=is_current))
            self.assertTrue(wrapper.queue_run_event(events, snapshot.run_id, "timeline", "two", is_current=is_current))
            lifecycle.invalidate()
            self.assertFalse(wrapper.queue_run_event(events, snapshot.run_id, "timeline", "stale", is_current=is_current))

        queued = self.drain(events)
        self.assertEqual([event.sequence for event in queued], [1, 2])
        self.assertFalse(wrapper.event_matches_run(queued[0], lifecycle.active_run_id, lifecycle.closed))
        self.assertNotIn("stale", str(queued))

    def test_queue_boundary_redacts_api_and_bearer_values(self):
        raw_key = "raw-timeline-api-key-123456"
        raw_bearer = "raw-timeline-bearer-123456"
        events = queue.Queue()
        wrapper.queue_run_event(
            events,
            "redaction-run",
            "timeline",
            f"api_key={raw_key}; Authorization: Bearer {raw_bearer}",
            secrets=[raw_key],
        )
        event = events.get_nowait()
        self.assertNotIn(raw_key, event.payload)
        self.assertNotIn(raw_bearer, event.payload)
        self.assertIn("[redacted]", event.payload)

    def test_proposal_is_queued_only_after_complete_valid_json(self):
        host = WorkerHost()
        response_text = '{"summary":"complete","files":[{"path":"note.txt","content":"after"}]}'
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root, run_id="proposal-stream-run")
            host.lifecycle.activate(snapshot)
            response = streamed_response(
                [response_text[:20], response_text[20:55], response_text[55:]],
                split_at=11,
            )
            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=(["coding:free"], None)),
                mock.patch.object(wrapper, "urlopen", return_value=response),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe instruction")

            events = self.drain(host.work_queue)

        stream_sequences = [event.sequence for event in events if event.kind == "stream_delta"]
        proposal_events = [event for event in events if event.kind == "proposal"]
        self.assertTrue(stream_sequences)
        self.assertEqual(len(proposal_events), 1)
        self.assertLess(max(stream_sequences), proposal_events[0].sequence)
        self.assertEqual("".join(event.payload for event in events if event.kind == "stream_delta"), response_text)
        self.assertFalse((root / "note.txt").exists())

    def test_context_too_small_returns_no_eligible_without_provider_call(self):
        candidate = {
            "id": "small:free",
            "pricing": {"prompt": "0", "completion": "0"},
            "context_length": 128,
        }
        selected, reason = wrapper.select_free_model_candidate([candidate], task_context_tokens=512)
        self.assertIsNone(selected)
        self.assertIn("no eligible", reason)

        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter") as provider:
            with self.assertRaisesRegex(RuntimeError, "No explicitly free"):
                wrapper.call_openrouter_with_fallback(
                    "safe-key",
                    "safe",
                    [],
                    [],
                    events,
                    "too-small-run",
                    model_queue=[candidate],
                    task_context_tokens=512,
                )
        provider.assert_not_called()

    def test_discovered_candidates_stay_ahead_of_static_candidates(self):
        discovered = wrapper.FreeModelCandidate(
            "discovered/model",
            free_proof_source=wrapper.FREE_PROOF_ZERO_PRICING,
            pricing={"prompt": "0", "completion": "0"},
            source=wrapper.MODEL_SOURCE_DISCOVERED,
        )
        static = wrapper.FreeModelCandidate(
            "static:free",
            free_proof_source=wrapper.FREE_PROOF_STATIC,
            source=wrapper.MODEL_SOURCE_STATIC,
            static_order=0,
            context_length=4096,
        )
        ranked = wrapper.rank_free_model_candidates([static, discovered], task_context_tokens=100)
        self.assertEqual(ranked[0].source, wrapper.MODEL_SOURCE_DISCOVERED)
        self.assertEqual(ranked[0].model_id, "discovered/model")


if __name__ == "__main__":
    unittest.main()
