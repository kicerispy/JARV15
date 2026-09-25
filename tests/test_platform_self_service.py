import json
import unittest

import planner
from smart_router import route_command


class PlatformSelfServiceTests(unittest.TestCase):
    def test_router_sends_self_diagnostics_to_agent(self):
        decision = route_command("check yourself")
        self.assertEqual(decision.mode, "agent")

    def test_planner_builds_doctor_route_without_llm(self):
        plan = planner.create_plan("run a full self test")
        self.assertEqual(plan["steps"][0]["tool"], "jarvis_doctor")
        payload = json.loads(plan["steps"][0]["argument"])
        self.assertTrue(payload["deep"])
        self.assertTrue(payload["run_tests"])

    def test_planner_builds_memory_recall_route_without_llm(self):
        plan = planner.create_plan("what do you remember")
        self.assertEqual(plan["steps"][0]["tool"], "memory_recall")
        payload = json.loads(plan["steps"][0]["argument"])
        self.assertEqual(payload["limit"], 10)

    def test_planner_builds_forget_route_without_llm(self):
        plan = planner.create_plan("forget that my favorite model is qwen")
        self.assertEqual(plan["steps"][0]["tool"], "memory_forget")


if __name__ == "__main__":
    unittest.main()
