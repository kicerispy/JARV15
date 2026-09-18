import unittest
from unittest import mock


class ModelManagerTests(unittest.TestCase):

    def test_model_roles_are_centralized(self):
        from model_manager import ModelManager

        manager = ModelManager()

        self.assertEqual(manager.chat_model, "qwen3.5:9b")
        self.assertEqual(manager.planner_model, "qwen3.5:9b")
        self.assertEqual(manager.coding_model, "qwen2.5-coder:14b")
        self.assertEqual(manager.coding_fallback_model, "gemma4:26b")
        self.assertEqual(manager.coding_num_ctx, 8192)

    def test_chat_generation_defaults_are_centralized(self):
        from model_manager import ModelManager

        manager = ModelManager()

        self.assertFalse(manager.chat_think)
        self.assertEqual(manager.chat_num_gpu, 40)
        self.assertEqual(manager.chat_num_predict, 220)


    def test_warmup_coding_model_uses_tiny_generation(self):
        from model_manager import ModelManager
        import model_manager

        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {"message": {"content": "OK"}}

        original = model_manager.config.PRELOAD_CODING_MODEL
        model_manager.config.PRELOAD_CODING_MODEL = True
        try:
            with mock.patch("ollama.chat", side_effect=fake_chat):
                self.assertTrue(ModelManager().warmup_coding_model())
        finally:
            model_manager.config.PRELOAD_CODING_MODEL = original

        self.assertEqual(captured.get("model"), ModelManager().coding_model)
        self.assertEqual(
            captured.get("options"),
            {
                "temperature": 0,
                "num_predict": 1,
                "num_ctx": ModelManager().coding_num_ctx,
            },
        )
        self.assertEqual(
            captured.get("keep_alive"),
            model_manager.config.CODING_MODEL_KEEP_ALIVE,
        )

    def test_coding_model_warmup_can_be_disabled(self):
        from model_manager import ModelManager
        import model_manager

        original = model_manager.config.PRELOAD_CODING_MODEL
        model_manager.config.PRELOAD_CODING_MODEL = False
        try:
            self.assertFalse(ModelManager().warmup_coding_model())
        finally:
            model_manager.config.PRELOAD_CODING_MODEL = original


if __name__ == "__main__":
    unittest.main()
