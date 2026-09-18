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

    def test_multi_step_request_routes_agent(self):
        from smart_router import route_command

        decision = route_command(
            "Open Chrome and search YouTube for Iron Man"
        )

        self.assertEqual(decision.kind, "agent")


if __name__ == "__main__":
    unittest.main()
