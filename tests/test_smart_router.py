import unittest


class SmartRouterTests(unittest.TestCase):

    def test_simple_command_routes_fast(self):
        from smart_router import RouteDecision, route_command

        decision = route_command("Open Chrome")

        self.assertIsInstance(decision, RouteDecision)
        self.assertEqual(decision.kind, "fast")

    def test_creative_request_routes_conversation(self):
        from smart_router import route_command

        decision = route_command("Tell me a joke")

        self.assertEqual(decision.kind, "conversation")

    def test_normal_question_routes_conversation(self):
        from smart_router import route_command

        decision = route_command("What can you do?")

        self.assertEqual(decision.kind, "conversation")

    def test_search_result_summary_followups_route_contextual(self):
        from smart_router import route_command

        for command in (
            "What are the search results?",
            "Tell me the search results",
            "Show me the search results",
            "What did the search find?",
            "What did you find?",
        ):
            decision = route_command(command)
            self.assertEqual(
                decision.kind,
                "contextual",
                command,
            )

    def test_direct_browser_url_routes_fast(self):
        from smart_router import route_command

        for command in (
            "Go to https://www.python.org",
            "Navigate to https://www.example.com/docs",
            "Visit www.python.org",
        ):
            decision = route_command(command)
            self.assertEqual(
                decision.kind,
                "fast",
                command,
            )


    def test_multi_step_request_routes_agent(self):
        from smart_router import route_command

        decision = route_command(
            "Open Chrome and search YouTube for Iron Man"
        )

        self.assertEqual(decision.kind, "agent")


    def test_ordinal_result_followups_route_contextual(self):
        from smart_router import route_command

        for command in (
            "Click the second result",
            "Choose the third result",
            "Open the last link",
        ):
            decision = route_command(command)
            self.assertEqual(
                decision.kind,
                "contextual",
                command,
            )


if __name__ == "__main__":
    unittest.main()
