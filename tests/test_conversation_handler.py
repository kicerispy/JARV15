import unittest
from unittest import mock


class ConversationSpeechPipelineTests(unittest.TestCase):

    def test_long_reply_is_split_before_tts(self):
        import conversation_handler

        long_reply = (
            "First sentence explains the result clearly. "
            "Second sentence contains additional context so the response "
            "is long enough to require multiple speech chunks. "
            "Third sentence finishes the explanation without dropping any "
            "of the original content."
        )

        spoken = []

        with mock.patch.object(
            conversation_handler,
            "build_conversation_messages",
            return_value=[
                {"role": "user", "content": "Explain this."}
            ],
        ), mock.patch.object(
            conversation_handler.MODEL_MANAGER,
            "chat",
            return_value={
                "message": {
                    "content": long_reply,
                }
            },
        ), mock.patch(
            "conversation_handler.add_message",
        ):
            result = conversation_handler.handle_normal_conversation(
                "Explain this.",
                mock.Mock(),
                "system prompt",
                lambda text: spoken.append(text) or False,
            )

        self.assertEqual(result, "done")
        self.assertGreater(len(spoken), 1)
        self.assertLessEqual(max(len(chunk) for chunk in spoken), 320)

        reconstructed = " ".join(spoken)

        self.assertIn("First sentence explains the result clearly.", reconstructed)
        self.assertIn(
            "Third sentence finishes the explanation without dropping any of the original content.",
            reconstructed,
        )


if __name__ == "__main__":
    unittest.main()
