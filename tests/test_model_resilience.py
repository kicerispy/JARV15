import unittest
from unittest.mock import patch

import config
from model_manager import ModelGenerationError, ModelManager


class ModelResilienceTests(unittest.TestCase):
    def test_coding_falls_back_to_configured_model_after_primary_failure(self):
        manager = ModelManager(
            coding_model="primary-coder",
            coding_fallback_model="fallback-coder",
        )
        sentinel = object()

        with patch.object(
            manager,
            "generate",
            side_effect=[
                ModelGenerationError("primary unavailable", attempts=2, retryable=True),
                sentinel,
            ],
        ) as generate:
            result = manager.coding([{"role": "user", "content": "repair this"}])

        self.assertIs(result, sentinel)
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args_list[1].kwargs["model"], "fallback-coder")

    def test_model_inventory_uses_ollama_tags_endpoint(self):
        manager = ModelManager()

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"models":[{"name":"qwen3.5:9b"},{"name":"gemma4:e2b"}]}'

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            models = manager.list_local_models()

        self.assertEqual(
            [item["name"] for item in models],
            ["qwen3.5:9b", "gemma4:e2b"],
        )


if __name__ == "__main__":
    unittest.main()
