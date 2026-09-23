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

# WebRTC's realtime example uses 10 ms frames at 16 kHz. Keeping the wrapper
# on that frame boundary avoids oversized-vector problems in native bindings
# while preserving stateful AEC processing across sequential frames.
AEC_FRAME_MS = 10


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

        frame_samples = max(
            1,
            int(round(self.sample_rate * AEC_FRAME_MS / 1000.0)),
        )

        cleaned_parts = []
        for start in range(0, len(mic), frame_samples):
            end = min(start + frame_samples, len(mic))

            mic_frame = mic[start:end]
            far_frame = far[start:end]

            original_len = len(mic_frame)
            if original_len < frame_samples:
                pad_width = frame_samples - original_len
                mic_frame = np.pad(
                    mic_frame,
                    (0, pad_width),
                )
                far_frame = np.pad(
                    far_frame,
                    (0, pad_width),
                )

            cleaned_frame = self.processor.process(
                mic_frame,
                far_frame,
            )

            cleaned_parts.append(
                np.asarray(
                    cleaned_frame,
                    dtype=mic.dtype,
                ).reshape(-1)[:original_len]
            )

        if not cleaned_parts:
            return mic

        return np.concatenate(cleaned_parts).astype(
            mic.dtype,
            copy=False,
        )


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
