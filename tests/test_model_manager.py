import unittest


class ModelManagerTests(unittest.TestCase):

    def test_model_roles_are_centralized(self):
        from model_manager import ModelManager

        manager = ModelManager()

        self.assertEqual(manager.chat_model, "qwen3.5:9b")
        self.assertEqual(manager.planner_model, "qwen3.5:9b")
        self.assertEqual(manager.coding_model, "gemma4:26b")

    def test_chat_generation_defaults_are_centralized(self):
        from model_manager import ModelManager

        manager = ModelManager()

        self.assertFalse(manager.chat_think)
        self.assertEqual(manager.chat_num_gpu, 40)
        self.assertEqual(manager.chat_num_predict, 220)


if __name__ == "__main__":
    unittest.main()
