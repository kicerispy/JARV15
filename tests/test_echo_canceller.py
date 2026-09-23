import unittest

import numpy as np

from echo_canceller import SpeakerEchoCanceller


class _RecordingProcessor:
    def __init__(self):
        self.calls = []

    def process(self, near, far):
        self.calls.append((len(near), len(far)))
        assert len(near) == len(far) == 160
        return np.asarray(near)


class EchoCancellerFrameChunkingTests(unittest.TestCase):

    def _make_canceller(self):
        canceller = object.__new__(SpeakerEchoCanceller)
        canceller.sample_rate = 16000
        canceller.stream_delay_ms = 80
        canceller.processor = _RecordingProcessor()
        return canceller

    def test_process_uses_10ms_frames_and_preserves_length(self):
        canceller = self._make_canceller()

        mic = np.arange(1024, dtype=np.int16)
        far = np.arange(1024, dtype=np.int16)

        cleaned = canceller.process(mic, far)

        self.assertEqual(len(cleaned), 1024)
        self.assertEqual(
            canceller.processor.calls,
            [(160, 160), (160, 160), (160, 160), (160, 160),
             (160, 160), (160, 160), (160, 160)],
        )
        np.testing.assert_array_equal(cleaned, mic)

    def test_process_pads_only_final_partial_frame(self):
        canceller = self._make_canceller()

        mic = np.arange(170, dtype=np.int16)
        far = np.arange(170, dtype=np.int16)

        cleaned = canceller.process(mic, far)

        self.assertEqual(len(cleaned), 170)
        self.assertEqual(
            canceller.processor.calls,
            [(160, 160), (160, 160)],
        )
        np.testing.assert_array_equal(cleaned, mic)

    def test_process_empty_audio_returns_empty_audio(self):
        canceller = self._make_canceller()

        mic = np.array([], dtype=np.int16)
        far = np.array([], dtype=np.int16)

        cleaned = canceller.process(mic, far)

        self.assertEqual(len(cleaned), 0)
        self.assertEqual(canceller.processor.calls, [])


if __name__ == "__main__":
    unittest.main()
