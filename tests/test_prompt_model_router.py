import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


def free_record(model_id, context_length=4096, description="", capabilities=None, pricing=None):
    record = {
        "id": model_id,
        "pricing": pricing or {"prompt": "0", "completion": "0"},
        "context_length": context_length,
    }
    if description:
        record["description"] = description
    if capabilities is not None:
        record["capabilities"] = capabilities
    return record


class PromptModelRouterTests(unittest.TestCase):
    def test_prompt_categories_cover_specialized_requests(self):
        self.assertEqual(wrapper.classify_prompt_category("Debug this Python API and update the README"), "coding")
        self.assertEqual(wrapper.classify_prompt_category("Solve this algebra equation and prove the result"), "math")
        self.assertEqual(wrapper.classify_prompt_category("Rewrite this story as polished prose"), "writing")
        self.assertEqual(wrapper.classify_prompt_category("Translate this Slovenian text to English"), "translation")
        self.assertEqual(wrapper.classify_prompt_category("Inspect this image with OCR"), "vision")

    def test_category_fit_beats_generic_free_model(self):
        candidates = [
            free_record("meta-llama/llama:free", description="general assistant chat"),
            free_record("qwen/qwen3-coder:free", description="coding software engineering repository"),
        ]

        selected, reason = wrapper.select_free_model_candidate(
            candidates,
            task_context_tokens=100,
            task_category="coding",
        )

        self.assertEqual(selected.model_id, "qwen/qwen3-coder:free")
        self.assertIn("coding-matched", reason)

    def test_override_is_free_only_and_preferred_first(self):
        selected, reason = wrapper.select_free_model_candidate(
            [free_record("qwen/qwen3-coder:free")],
            task_category="coding",
            model_override="provider/manual:free",
        )

        self.assertEqual(selected.model_id, "provider/manual:free")
        self.assertIn("override-explicit-free", reason)
        with self.assertRaises(ValueError):
            wrapper.normalize_model_override("provider/manual:paid")
        with self.assertRaises(ValueError):
            wrapper.rank_free_model_candidates(
                [free_record("qwen/qwen3-coder:free")],
                task_category="coding",
                model_override="provider/manual:paid",
            )

    def test_zero_pricing_rejects_any_advertised_nonzero_cost(self):
        catalog = wrapper.FreeModelDiscoveryResult(
            [
                free_record(
                    "good/no-suffix",
                    pricing={"prompt": "0", "completion": "0", "request": "0", "image": "0"},
                ),
                free_record(
                    "good:free",
                    pricing={"prompt": "0", "completion": "0", "request": "0"},
                ),
                free_record(
                    "bad/no-suffix",
                    pricing={"prompt": "0", "completion": "0", "request": "1"},
                ),
                free_record(
                    "bad:free",
                    pricing={"prompt": "0", "completion": "0", "request": "1"},
                ),
            ]
        )

        self.assertEqual(list(catalog), ["good/no-suffix", "good:free"])

    def test_local_model_commands_and_snapshot_settings(self):
        self.assertEqual(wrapper.parse_model_selection_command("/model auto"), ("auto", ""))
        self.assertEqual(wrapper.parse_model_selection_command("/model reset"), ("auto", ""))
        self.assertEqual(
            wrapper.parse_model_selection_command("/model provider/manual:free"),
            ("override", "provider/manual:free"),
        )
        with self.assertRaises(ValueError):
            wrapper.parse_model_selection_command("/model provider/manual:paid")

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                project_root=Path(temp_dir),
                extra_context_paths=(),
                session_messages=(),
                apply_mode=wrapper.APPLY_MODE_REVIEW,
                model_selection_mode="override",
                model_override="provider/manual:free",
            )
        self.assertEqual(snapshot.model_selection_mode, "override")
        self.assertEqual(snapshot.model_override, "provider/manual:free")

    def test_busy_provider_falls_back_to_next_free_candidate(self):
        events = queue.Queue()
        with mock.patch.object(
            wrapper,
            "call_openrouter",
            side_effect=[RuntimeError("OpenRouter HTTP 429: provider busy"), '{"summary":"ok","files":[]}'],
        ) as provider:
            result, model = wrapper.call_openrouter_with_fallback(
                api_key="safe-key",
                instructions="Implement a coding fix",
                files=[],
                session_messages=[],
                log_queue=events,
                run_id="router-run",
                event_is_current=lambda: True,
                model_queue=["fallback:free"],
                model_selection_mode="override",
                model_override="provider/manual:free",
            )

        self.assertEqual(model, "fallback:free")
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(
            [call.args[1] for call in provider.call_args_list],
            ["provider/manual:free", "fallback:free"],
        )
        self.assertIn("busy/rate-limited", str(list(events.queue)))


if __name__ == "__main__":
    unittest.main()
