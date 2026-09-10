import unittest

import command_suggestions as suggestions


class CommandSuggestionTests(unittest.TestCase):
    def test_context_and_prompt_choose_the_inline_recommendation(self):
        review = suggestions.recommend_local_command(
            "/",
            prompt="Fix the Python API and update the README",
            task_state="review",
            pending_edits=2,
        )
        self.assertEqual(review.completion, "/review")
        self.assertEqual(review.suffix, "review")
        self.assertIn("pending review", review.reason)
        self.assertEqual(review.category, "coding")

        active = suggestions.recommend_local_command(
            "/",
            prompt="Summarize the research notes",
            task_state="running",
        )
        self.assertEqual(active.completion, "/status")
        self.assertIn("active run", active.reason)

    def test_prefix_completion_and_model_subcommands(self):
        self.assertEqual(
            suggestions.recommend_local_command("/st").completion,
            "/status",
        )
        self.assertEqual(
            suggestions.recommend_local_command("/model a").completion,
            "/model auto",
        )
        self.assertEqual(
            suggestions.recommend_local_command("/model r").completion,
            "/model reset",
        )
        self.assertIsNone(suggestions.recommend_local_command("/status"))

    def test_completion_is_advisory_and_unknown_input_has_no_suggestion(self):
        recommendation = suggestions.recommend_local_command("/per")
        self.assertEqual(recommendation.typed, "/per")
        self.assertEqual(recommendation.completion, "/permissions")
        self.assertEqual(recommendation.suffix, "missions")
        self.assertIsNone(suggestions.recommend_local_command("run a command"))
        self.assertIsNone(suggestions.recommend_local_command("/shell"))


if __name__ == "__main__":
    unittest.main()
