import unittest
from unittest.mock import patch

from conversation_handler import handle_normal_conversation
from state import ActiveContext
import conversation_handler


class ChatGenerationConfigTests(unittest.TestCase):

    def test_normal_conversation_uses_bounded_chat_generation(self):
        captured = {}

        def fake_generate(
            *,
            model,
            messages,
            format=None,
            options=None,
            keep_alive=None,
            think=None,
        ):
            captured.update(
                {
                    "model": model,
                    "messages": messages,
                    "format": format,
                    "options": options,
                    "keep_alive": keep_alive,
                    "think": think,
                }
            )
            return {"message": {"content": "ok"}}

        with patch.object(
            conversation_handler.ModelManager,
            "generate",
            side_effect=fake_generate,
        ):
            with patch(
                "conversation_handler.build_conversation_messages",
                return_value=[
                    {"role": "system", "content": "test"},
                    {"role": "user", "content": "hello"},
                ],
            ):
                with patch("conversation.add_message"):
                    with patch.object(
                        conversation_handler.logger,
                        "info",
                    ):
                        status = handle_normal_conversation(
                            "hello",
                            ActiveContext(),
                            "test",
                            lambda text: False,
                        )

        self.assertEqual(status, "done")
        self.assertEqual(captured["model"], "qwen3.5:9b")
        self.assertFalse(captured["think"])
        self.assertEqual(captured["options"]["num_gpu"], 40)
        self.assertEqual(captured["options"]["num_predict"], 220)


if __name__ == "__main__":
    unittest.main()
