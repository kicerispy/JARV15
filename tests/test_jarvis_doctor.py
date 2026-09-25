import unittest
from unittest.mock import patch

import jarvis_doctor


class JarvisDoctorTests(unittest.TestCase):
    def test_doctor_reports_healthy_without_network_or_process_probes(self):
        health = {
            "overall": "READY",
            "ollama": True,
            "whisper": True,
            "piper": True,
        }
        models = {
            "reachable": True,
            "available_count": 2,
            "configured": {"chat": "qwen", "planner": "qwen"},
            "missing_configured_models": {},
        }

        with patch.object(jarvis_doctor.runtime_health, "collect_health", return_value=health),              patch.object(jarvis_doctor, "_check_models", return_value=models),              patch.object(jarvis_doctor, "healing_status", return_value={"events": 0}),              patch.object(jarvis_doctor, "autonomy_memory_status", return_value={"episodes": 0}),              patch.object(jarvis_doctor, "memory_status", return_value={"records": 0}),              patch.object(jarvis_doctor, "tool_health_status", return_value={"tool_count": 0, "degraded_tools": []}),              patch.object(jarvis_doctor, "_git_snapshot", return_value={"available": True}):
            result = jarvis_doctor.run_doctor()

        self.assertTrue(result["success"])
        self.assertEqual(result["failures"], [])

    def test_doctor_flags_missing_configured_model(self):
        health = {
            "overall": "READY",
            "ollama": True,
            "whisper": True,
            "piper": True,
        }
        models = {
            "reachable": True,
            "available_count": 1,
            "configured": {"chat": "qwen"},
            "missing_configured_models": {"chat": "qwen"},
        }

        with patch.object(jarvis_doctor.runtime_health, "collect_health", return_value=health),              patch.object(jarvis_doctor, "_check_models", return_value=models),              patch.object(jarvis_doctor, "healing_status", return_value={"events": 0}),              patch.object(jarvis_doctor, "autonomy_memory_status", return_value={"episodes": 0}),              patch.object(jarvis_doctor, "memory_status", return_value={"records": 0}),              patch.object(jarvis_doctor, "tool_health_status", return_value={"tool_count": 0, "degraded_tools": []}),              patch.object(jarvis_doctor, "_git_snapshot", return_value={"available": True}):
            result = jarvis_doctor.run_doctor()

        self.assertFalse(result["success"])
        self.assertTrue(any("not installed" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
