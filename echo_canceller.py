"""
WebRTC AEC3 wrapper for JARVIS speaker/microphone audio.

The module is intentionally optional. If pywebrtc-audio is unavailable,
JARVIS can continue using its existing playback-reference echo heuristics.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np


DEFAULT_STREAM_DELAY_MS = int(
    os.environ.get(
        "JARVIS_AEC_STREAM_DELAY_MS",
        "80",
    )
)


class SpeakerEchoCanceller:
    """Stateful WebRTC AEC3 processor for one microphone thread."""

    def __init__(
        self,
        sample_rate: int = 16000,
        stream_delay_ms: Optional[int] = None,
    ) -> None:
        from pywebrtc_audio import AudioProcessor

        self.sample_rate = int(sample_rate)
        self.stream_delay_ms = (
            DEFAULT_STREAM_DELAY_MS
            if stream_delay_ms is None
            else int(stream_delay_ms)
        )

        self.processor = AudioProcessor(
            sample_rate=self.sample_rate,
            num_channels=1,
            echo_cancellation=True,
            noise_suppression=True,
            auto_gain_control=False,
            stream_delay_ms=self.stream_delay_ms,
        )

    @property
    def available(self) -> bool:
        return True

    @property
    def speech_probability(self) -> float:
        try:
            return float(
                self.processor.speech_probability
            )
        except Exception:
            return 0.0

    def reset(self) -> None:
        self.processor.reset()

    def process(
        self,
        microphone_audio: np.ndarray,
        speaker_reference: np.ndarray,
    ) -> np.ndarray:
        """
        Remove speaker echo from microphone_audio.

        Both signals are 16 kHz mono int16 or float32 arrays. The returned
        array has the same dtype and length as microphone_audio.
        """
        mic = np.asarray(
            microphone_audio
        ).reshape(-1)

        far = np.asarray(
            speaker_reference
        ).reshape(-1)

        if len(mic) == 0:
            return mic

        if len(far) != len(mic):
            if len(far) == 0:
                far = np.zeros_like(
                    mic
                )
            elif len(far) < len(mic):
                far = np.pad(
                    far,
                    (0, len(mic) - len(far)),
                )
            else:
                far = far[:len(mic)]

        cleaned = self.processor.process(
            mic,
            far,
        )

        return np.asarray(
            cleaned,
            dtype=mic.dtype,
        ).reshape(-1)


def create_echo_canceller() -> Optional[SpeakerEchoCanceller]:
    """Create AEC3 when the optional WebRTC binding is installed."""
    try:
        canceller = SpeakerEchoCanceller()

        print(
            "JARVIS AEC: WebRTC AEC3 ready "
            f"(stream_delay_ms={canceller.stream_delay_ms})."
        )

        return canceller

    except Exception as exc:
        print(
            "JARVIS AEC: WebRTC AEC3 unavailable; "
            f"using playback-reference fallback ({exc})"
        )

        return None
