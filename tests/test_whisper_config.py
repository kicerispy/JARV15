import unittest

import config


class WhisperConfigTests(unittest.TestCase):

    def test_whisper_defaults_to_cpu_int8(self):
        self.assertEqual(config.WHISPER_DEVICE, "cpu")
        self.assertEqual(config.WHISPER_COMPUTE_TYPE, "int8")

    def test_whisper_model_default_is_small_english(self):
        self.assertEqual(config.WHISPER_MODEL, "small.en")


if __name__ == "__main__":
    unittest.main()
