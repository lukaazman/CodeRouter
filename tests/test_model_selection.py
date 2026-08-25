import queue
import unittest
from unittest import mock

import codex_free_wrapper as wrapper


def free_record(model_id, context_length=None, capabilities=None):
    record = {
        "id": model_id,
        "pricing": {"prompt": "0", "completion": "0"},
    }
    if context_length is not None:
        record["context_length"] = context_length
    if capabilities is not None:
        record["capabilities"] = capabilities
    return record


class ModelSelectionTests(unittest.TestCase):
    def test_catalog_order_does_not_change_ranking(self):
        records = [
            free_record("zeta/general", context_length=4096),
            free_record("alpha/general", context_length=4096),
        ]

        first = wrapper.rank_free_model_candidates(records, task_context_tokens=100)
        second = wrapper.rank_free_model_candidates(list(reversed(records)), task_context_tokens=100)

        self.assertEqual([candidate.model_id for candidate in first], ["alpha/general", "zeta/general"])
        self.assertEqual(
            [candidate.model_id for candidate in first],
            [candidate.model_id for candidate in second],
        )

    def test_paid_and_missing_metadata_are_rejected(self):
        catalog = wrapper.FreeModelDiscoveryResult(
            [
                free_record("verified/plain"),
                {"id": "paid/plain", "pricing": {"prompt": "0.01", "completion": "0"}},
                {"id": "missing/plain"},
                {"id": "paid:free", "pricing": {"prompt": "0.01", "completion": "0"}},
            ]
        )

        self.assertEqual(list(catalog), ["verified/plain"])
        self.assertEqual(wrapper._filter_free_model_queue(["paid/plain", "missing/plain"]), [])
        candidate = catalog[0]
        self.assertEqual(candidate.free_proof_source, wrapper.FREE_PROOF_ZERO_PRICING)
        self.assertEqual(candidate.pricing["prompt"], "0")
        self.assertEqual(candidate.source, wrapper.MODEL_SOURCE_DISCOVERED)

    def test_context_fit_is_preferred_before_other_signals(self):
        candidates = [
            free_record("small/coder", context_length=128, capabilities={"coding": True}),
            free_record("large/general", context_length=4096),
        ]

        selected, reason = wrapper.select_free_model_candidate(candidates, task_context_tokens=512)

        self.assertEqual(selected.model_id, "large/general")
        self.assertIn("context-fit", reason)

    def test_explicit_coding_capability_is_preferred_when_context_fits(self):
        candidates = [
            free_record("generic/model", context_length=4096),
            free_record("coding/model", context_length=4096, capabilities={"coding": True}),
        ]

        selected, reason = wrapper.select_free_model_candidate(candidates, task_context_tokens=512)

        self.assertEqual(selected.model_id, "coding/model")
        self.assertIn("coding-capable", reason)
        self.assertTrue(selected.capability_signals)

    def test_ties_are_deterministic_by_id(self):
        candidates = [
            free_record("beta/model", context_length=4096),
            free_record("alpha/model", context_length=4096),
        ]

        selected_a, reason_a = wrapper.select_free_model_candidate(candidates, task_context_tokens=100)
        selected_b, reason_b = wrapper.select_free_model_candidate(list(reversed(candidates)), task_context_tokens=100)

        self.assertEqual(selected_a.model_id, "alpha/model")
        self.assertEqual(selected_a.model_id, selected_b.model_id)
        self.assertEqual(reason_a, reason_b)

    def test_static_fallback_preserves_known_order_and_source(self):
        static_models = ["zeta:free", "alpha:free"]
        candidates, note = wrapper.build_free_model_queue(
            "safe-key",
            discovery_fn=mock.Mock(side_effect=TimeoutError("bounded timeout")),
            static_models=static_models,
        )

        self.assertEqual(list(candidates), static_models)
        self.assertIsNotNone(note)
        self.assertTrue(all(candidate.source == wrapper.MODEL_SOURCE_STATIC for candidate in candidates))
        selected, reason = wrapper.select_free_model_candidate(
            candidates,
            task_context_tokens=100,
            default_source=wrapper.MODEL_SOURCE_STATIC,
        )
        self.assertEqual(selected.model_id, "zeta:free")
        self.assertIn("static-known-free", reason)

    def test_selection_status_uses_run_id_and_explainable_reason(self):
        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter", return_value='{"summary":"ok","files":[]}'):
            result, model = wrapper.call_openrouter_with_fallback(
                api_key="safe-key",
                instructions="safe",
                files=[],
                session_messages=[],
                log_queue=events,
                run_id="selection-run",
                event_is_current=lambda: True,
                model_queue=[free_record("coding/model", context_length=4096, capabilities={"coding": True})],
                task_context_tokens=100,
            )

        self.assertEqual(model, "coding/model")
        self.assertEqual(result["summary"], "ok")
        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        self.assertTrue(all(event[0] == "selection-run" for event in queued))
        selected_statuses = [event[2] for event in queued if event[1] == "model_status"]
        self.assertEqual(len(selected_statuses), 1)
        self.assertIn("Selected free model: coding/model", selected_statuses[0])
        self.assertIn("context-fit", selected_statuses[0])
        self.assertIn("coding-capable", selected_statuses[0])

    def test_cancellation_stops_selection_before_next_candidate(self):
        events = queue.Queue()
        active = {"value": True}

        def fail_first(*_args):
            active["value"] = False
            raise RuntimeError("transient failure")

        with mock.patch.object(wrapper, "call_openrouter", side_effect=fail_first) as provider:
            with self.assertRaises(wrapper.RunCancelledError):
                wrapper.call_openrouter_with_fallback(
                    api_key="safe-key",
                    instructions="safe",
                    files=[],
                    session_messages=[],
                    log_queue=events,
                    run_id="cancel-selection-run",
                    event_is_current=lambda: active["value"],
                    model_queue=["first:free", "second:free"],
                )

        self.assertEqual(provider.call_count, 1)
        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        self.assertTrue(all(event[0] == "cancel-selection-run" for event in queued))
        self.assertNotIn("second:free", str(queued))

    def test_provider_error_redaction_happens_before_fallback_events(self):
        raw_api_key = "raw-selector-api-key-123456"
        raw_bearer = "raw-selector-bearer-123456"
        events = queue.Queue()
        error = RuntimeError(f"api_key={raw_api_key}; Authorization: Bearer {raw_bearer}")

        with mock.patch.object(wrapper, "call_openrouter", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                wrapper.call_openrouter_with_fallback(
                    api_key=raw_api_key,
                    instructions="safe",
                    files=[],
                    session_messages=[],
                    log_queue=events,
                    run_id="redaction-selection-run",
                    model_queue=["one:free"],
                )

        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        text = str(queued) + str(raised.exception)
        self.assertNotIn(raw_api_key, text)
        self.assertNotIn(raw_bearer, text)
        self.assertIn("[redacted]", text)


if __name__ == "__main__":
    unittest.main()
