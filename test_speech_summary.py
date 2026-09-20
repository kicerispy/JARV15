"""Focused regression tests for structured API speech summaries."""

import unittest

from tool_executor import _api_spoken_summary
from tool_result import ToolResult


class ApiSpeechSummaryTests(unittest.TestCase):
    def setUp(self):
        self.currency = {
            "amount": 100,
            "base": "USD",
            "quote": "EUR",
            "converted": 87.005,
            "rate": 0.87005,
        }

    def test_direct_toolresult_payload(self):
        result = ToolResult(
            success=True,
            tool="currency_convert",
            data=self.currency,
        )

        summary = _api_spoken_summary(
            "currency_convert",
            result,
        )

        self.assertEqual(
            summary,
            "100 USD is 87.00 EUR. The exchange rate is 0.87005.",
        )

    def test_wrapped_toolresult_payload(self):
        result = ToolResult(
            success=True,
            tool="currency_convert",
            data={
                "success": True,
                "data": self.currency,
            },
        )

        summary = _api_spoken_summary(
            "currency_convert",
            result,
        )

        self.assertEqual(
            summary,
            "100 USD is 87.00 EUR. The exchange rate is 0.87005.",
        )

    def test_legacy_dict_payload(self):
        summary = _api_spoken_summary(
            "currency_convert",
            {
                "success": True,
                "data": self.currency,
            },
        )

        self.assertEqual(
            summary,
            "100 USD is 87.00 EUR. The exchange rate is 0.87005.",
        )

    def test_currency_legacy_from_to_shape(self):
        summary = _api_spoken_summary(
            "currency_convert",
            ToolResult(
                success=True,
                tool="currency_convert",
                data={
                    "amount": 100,
                    "from": "USD",
                    "to": "EUR",
                    "converted": 87.0,
                    "rate": 0.87,
                },
            ),
        )
        self.assertEqual(
            summary,
            "100 USD is 87.00 EUR. The exchange rate is 0.87000.",
        )

    def test_location_direct_payload(self):
        result = ToolResult(
            success=True,
            tool="location_lookup",
            data={
                "results": [
                    {
                        "name": "Chicago",
                        "country": "United States",
                        "timezone": "America/Chicago",
                    }
                ],
            },
        )

        self.assertEqual(
            _api_spoken_summary("location_lookup", result),
            "Chicago is in United States. The timezone is America/Chicago.",
        )


if __name__ == "__main__":
    unittest.main()
