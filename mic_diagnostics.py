"""
JARVIS microphone signal diagnostics.

Measures the same raw int16 microphone signal used by speech.py and reports
RMS, peak, dBFS, clipping, and the adaptive speech-gate thresholds. It is
intended to diagnose the MV7X -> interface -> Windows -> JARVIS signal path
without changing any JARVIS runtime settings.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from adaptive_speech_gate import AdaptiveSpeechGate
from config import CHUNK_SIZE, MIC_DEVICE, SAMPLE_RATE, SILENCE_THRESHOLD


@dataclass(frozen=True)
class SignalStats:
    duration: float
    samples: int
    rms: float
    peak: int
    dbfs: float
    clip_percent: float
    above_legacy_gate_percent: float


def measure_signal(
    audio: np.ndarray,
    sample_rate: int,
) -> SignalStats:
    values = np.asarray(audio, dtype=np.int16).reshape(-1)

    if values.size == 0:
        return SignalStats(0.0, 0, 0.0, 0, -120.0, 0.0, 0.0)

    float_values = values.astype(np.float32)

    rms = float(
        np.sqrt(
            np.mean(
                np.square(float_values)
            )
        )
    )

    peak = int(
        np.max(
            np.abs(values.astype(np.int32))
        )
    )

    dbfs = (
        20.0 * math.log10(rms / 32768.0)
        if rms > 0
        else -120.0
    )

    clip_percent = float(
        np.mean(
            np.abs(values.astype(np.int32)) >= 32760
        )
        * 100.0
    )

    above_legacy_gate_percent = float(
        np.mean(
            np.abs(float_values) > SILENCE_THRESHOLD
        )
        * 100.0
    )

    return SignalStats(
        duration=values.size / sample_rate,
        samples=int(values.size),
        rms=rms,
        peak=peak,
        dbfs=dbfs,
        clip_percent=clip_percent,
        above_legacy_gate_percent=above_legacy_gate_percent,
    )


def capture(
    stream: sd.InputStream,
    seconds: float,
) -> np.ndarray:
    chunks: list[np.ndarray] = []
    total_chunks = max(
        1,
        math.ceil(seconds * SAMPLE_RATE / CHUNK_SIZE),
    )

    for _ in range(total_chunks):
        audio, overflowed = stream.read(CHUNK_SIZE)

        if overflowed:
            print("  warning: microphone overflow reported")

        mono = np.asarray(
            audio[:, 0],
            dtype=np.int16,
        )
        chunks.append(mono)

    return np.concatenate(chunks)


def summarize(
    label: str,
    audio: np.ndarray,
) -> SignalStats:
    stats = measure_signal(audio, SAMPLE_RATE)

    print()
    print(f"===== {label} =====")
    print(f"Duration:             {stats.duration:.2f}s")
    print(f"Samples:              {stats.samples}")
    print(f"RMS:                  {stats.rms:.1f}")
    print(f"Peak:                 {stats.peak}")
    print(f"RMS dBFS:             {stats.dbfs:.1f} dBFS")
    print(f"Clipping:             {stats.clip_percent:.3f}%")
    print(
        f"Samples > RMS {SILENCE_THRESHOLD}: "
        f"{stats.above_legacy_gate_percent:.1f}%"
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the JARVIS microphone signal path."
    )
    parser.add_argument(
        "--device",
        type=int,
        default=MIC_DEVICE,
        help=f"Input device index (default: {MIC_DEVICE})",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=5.0,
        help="Seconds per measurement phase (default: 5)",
    )
    args = parser.parse_args()

    if args.seconds <= 0:
        raise SystemExit("--seconds must be greater than 0")

    devices = sd.query_devices()
    device_info = devices[args.device]

    print()
    print("========================================")
    print("JARVIS MICROPHONE DIAGNOSTICS")
    print("========================================")
    print(f"Device index:     {args.device}")
    print(f"Device name:      {device_info['name']}")
    print(f"Max input chans:  {device_info['max_input_channels']}")
    print(f"Default SR:       {device_info['default_samplerate']}")
    print(f"JARVIS SR:        {SAMPLE_RATE}")
    print(f"Chunk size:       {CHUNK_SIZE}")
    print(f"Legacy RMS gate:  {SILENCE_THRESHOLD}")
    print()
    print("This test does not change JARVIS settings.")
    print("Keep the SC3 gain where you normally use it.")
    print("")

    input(
        "Phase 1: stay silent, then press Enter to start the 5-second noise-floor test..."
    )

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=CHUNK_SIZE,
        channels=1,
        dtype="int16",
        device=args.device,
    ) as stream:
        print("Listening for room noise...")
        noise_audio = capture(stream, args.seconds)

        print()
        input(
            "Phase 2: speak normally from your usual sitting position, then press Enter..."
        )
        print("Speak naturally for the full measurement window.")
        normal_audio = capture(stream, args.seconds)

        print()
        input(
            "Phase 3: move farther from the microphone to your usual farther position, then press Enter..."
        )
        print("Speak naturally for the full measurement window.")
        far_audio = capture(stream, args.seconds)

    noise = summarize("ROOM NOISE", noise_audio)
    normal = summarize("NORMAL DISTANCE SPEECH", normal_audio)
    far = summarize("FARTHER DISTANCE SPEECH", far_audio)

    gate = AdaptiveSpeechGate(
        legacy_threshold=float(SILENCE_THRESHOLD)
    )

    # Feed representative per-phase RMS values so the user can see what the
    # adaptive gate would do in a quiet room. This is diagnostic only.
    for value in [noise.rms] * 8:
        gate.update(value)

    print()
    print("===== SIGNAL PATH INTERPRETATION =====")
    print(
        f"Noise floor estimate: {gate.noise_floor:.1f} RMS"
    )
    print(
        f"Adaptive start gate:  {gate.start_threshold:.1f} RMS"
    )
    print(
        f"Adaptive end gate:    {gate.end_threshold:.1f} RMS"
    )

    def speech_margin(stats: SignalStats) -> float:
        if gate.start_threshold <= 0:
            return 0.0
        return stats.rms / gate.start_threshold

    print()
    print(
        f"Normal-distance speech / adaptive start: "
        f"{speech_margin(normal):.2f}x"
    )
    print(
        f"Far-distance speech / adaptive start:    "
        f"{speech_margin(far):.2f}x"
    )

    print()
    if far.rms < gate.start_threshold:
        print(
            "RESULT: farther speech is below the adaptive speech-start level."
        )
        print(
            "The next place to investigate is the physical signal chain or"
            " input level, not another JARVIS threshold reduction."
        )
    elif far.rms < normal.rms * 0.40:
        print(
            "RESULT: farther speech drops sharply versus normal distance."
        )
        print(
            "This points toward microphone placement / interface gain / "
            "Windows input level as the limiting factor."
        )
    else:
        print(
            "RESULT: microphone levels remain reasonably strong at distance."
        )
        print(
            "That points back toward wake-word model sensitivity or temporal "
            "fusion rather than basic microphone level."
        )

    print()
    print(
        "Tip: compare these numbers before changing any SC3, Windows, or "
        "JARVIS settings."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
