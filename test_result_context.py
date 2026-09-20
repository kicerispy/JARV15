import unittest

from result_context import compact_context_description, resolve_result_followup
from state import ActiveContext


class StructuredResultContextTests(unittest.TestCase):

    def test_state_exposes_structured_result(self):
        context = ActiveContext()
        context.last_tool = "book_search"
        context.last_result = "I found 2 books."
        context.last_result_data = {
            "books": [
                {"title": "Dune", "authors": ["Frank Herbert"]},
                {"title": "Dune Messiah", "authors": ["Frank Herbert"]},
            ]
        }

        payload = context.to_dict()

        self.assertIn("last_result_data", payload)
        self.assertEqual(
            payload["last_result_data"]["books"][1]["title"],
            "Dune Messiah",
        )

    def test_second_book_reference(self):
        context = {
            "last_tool": "book_search",
            "last_result": "I found 2 books.",
            "last_result_data": {
                "books": [
                    {"title": "Dune", "authors": ["Frank Herbert"]},
                    {"title": "Dune Messiah", "authors": ["Frank Herbert"]},
                ]
            },
        }

        result = resolve_result_followup(
            "What was the second one?",
            context,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["index"], 1)
        self.assertEqual(
            result["selected"]["title"],
            "Dune Messiah",
        )
        self.assertIn("Dune Messiah", result["reply"])

    def test_last_alert_reference(self):
        context = {
            "last_tool": "weather_alerts",
            "last_result_data": {
                "count": 2,
                "alerts": [
                    {"event": "Flash Flood Warning"},
                    {"event": "Flood Advisory"},
                ],
            },
        }

        result = resolve_result_followup(
            "Tell me about the last one",
            context,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["index"], 1)
        self.assertIn("Flood Advisory", result["reply"])

    def test_knowledge_more(self):
        context = {
            "last_tool": "knowledge_lookup",
            "last_result_data": {
                "title": "Quantum computing",
                "summary": (
                    "Quantum computing is a type of computation that uses "
                    "quantum phenomena such as superposition and entanglement. "
                    "It can solve some problems differently from classical "
                    "computers. This is a third sentence."
                ),
            },
        }

        result = resolve_result_followup(
            "Tell me more about that",
            context,
        )

        self.assertIsNotNone(result)
        self.assertIn("Quantum computing", result["reply"])
        self.assertIn("superposition", result["reply"])

    def test_selected_result_expansion(self):
        context = {
            "last_tool": "research_arxiv",
            "last_result_data": {
                "papers": [
                    {
                        "title": "Paper One",
                        "authors": ["A. Author"],
                        "summary": (
                            "This paper studies retrieval. "
                            "It evaluates several methods. "
                            "It reports improved results."
                        ),
                    },
                    {
                        "title": "Paper Two",
                        "authors": ["B. Author"],
                        "summary": "A second paper.",
                    },
                ]
            },
            "last_result_index": 0,
            "last_selected_result": {
                "title": "Paper One",
                "authors": ["A. Author"],
                "summary": (
                    "This paper studies retrieval. "
                    "It evaluates several methods. "
                    "It reports improved results."
                ),
            },
        }

        result = resolve_result_followup(
            "Tell me more about that",
            context,
        )

        self.assertIsNotNone(result)
        self.assertIn("Paper One", result["reply"])
        self.assertIn("retrieval", result["reply"])

    def test_source_reference(self):
        context = {
            "last_tool": "knowledge_lookup",
            "last_result_data": {
                "title": "Alan Turing",
                "summary": "Alan Turing was a mathematician.",
                "url": "https://example.com/turing",
            },
        }

        result = resolve_result_followup(
            "What's the source",
            context,
        )

        self.assertIsNotNone(result)
        self.assertIn("example.com/turing", result["reply"])

    def test_browser_action_is_not_intercepted(self):
        context = {
            "last_tool": "book_search",
            "last_result_data": {
                "books": [
                    {"title": "Dune"},
                    {"title": "Dune Messiah"},
                ]
            },
        }

        result = resolve_result_followup(
            "Open the second one",
            context,
        )

        self.assertIsNone(result)

    def test_out_of_range_result(self):
        context = {
            "last_tool": "book_search",
            "last_result_data": {
                "books": [
                    {"title": "Dune"},
                    {"title": "Dune Messiah"},
                ]
            },
        }

        result = resolve_result_followup(
            "What was the fifth one?",
            context,
        )

        self.assertIsNotNone(result)
        self.assertIn("2 results", result["reply"])

    def test_field_followups(self):
        currency = {
            "last_tool": "currency_convert",
            "last_result_data": {
                "from": "USD",
                "to": "EUR",
                "rate": 0.87,
                "converted": 87.0,
            },
        }

        result = resolve_result_followup(
            "What was the exchange rate?",
            currency,
        )

        self.assertIsNotNone(result)
        self.assertIn("0.87", result["reply"])

        alerts = {
            "last_tool": "weather_alerts",
            "last_result_data": {
                "count": 3,
                "alerts": [],
            },
        }

        result = resolve_result_followup(
            "How many weather alerts were there?",
            alerts,
        )

        self.assertIsNotNone(result)
        self.assertIn("3", result["reply"])

    def test_new_queries_are_not_hijacked(self):
        currency = {
            "last_tool": "currency_convert",
            "last_result_data": {
                "from": "USD",
                "to": "EUR",
                "rate": 0.87,
            },
        }

        self.assertIsNone(
            resolve_result_followup(
                "What is the exchange rate for GBP?",
                currency,
            )
        )

        elevation = {
            "last_tool": "elevation_lookup",
            "last_result_data": {
                "location": {"name": "Chicago"},
                "elevation_meters": 179,
            },
        }

        self.assertIsNone(
            resolve_result_followup(
                "What is the elevation of Denver?",
                elevation,
            )
        )

    def test_no_context_does_not_intercept(self):
        result = resolve_result_followup(
            "What was the second one?",
            {},
        )
        self.assertIsNone(result)

    def test_compact_planner_context(self):
        context = {
            "last_tool": "book_search",
            "last_result_data": {
                "books": [
                    {"title": "Dune"},
                    {"title": "Dune Messiah"},
                ]
            },
        }

        compact = compact_context_description(context)

        self.assertIn("Result count available: 2", compact)
        self.assertIn("Result 1: Dune", compact)
        self.assertIn("Result 2: Dune Messiah", compact)


if __name__ == "__main__":
    unittest.main()
