import unittest

from typed_input import TypedInputChannel


class TypedInputChannelTests(unittest.TestCase):

    def test_enqueue_signals_interrupt_and_preserves_command(self):
        channel = TypedInputChannel(enabled=False)

        channel.enqueue_for_test("  open chrome  ")

        self.assertTrue(channel.has_pending())
        self.assertTrue(channel.interrupt_event.is_set())
        self.assertEqual(channel.get_nowait(), "open chrome")
        self.assertFalse(channel.has_pending())
        self.assertFalse(channel.interrupt_event.is_set())

    def test_disabled_channel_does_not_start_reader(self):
        channel = TypedInputChannel(enabled=False)

        self.assertFalse(channel.start())
        self.assertIsNone(channel.get_nowait())

    def test_empty_commands_are_ignored(self):
        channel = TypedInputChannel(enabled=False)

        channel.enqueue_for_test("   ")

        self.assertFalse(channel.has_pending())
        self.assertFalse(channel.interrupt_event.is_set())


if __name__ == "__main__":
    unittest.main()
