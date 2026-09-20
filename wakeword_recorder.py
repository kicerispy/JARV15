"""Local JARVIS wake-word dataset recorder.

Records short 16 kHz mono PCM WAV clips for personal Heed wake-word training.
Everything is written under the local wakeword_dataset directory and that
directory is intentionally ignored by Git. Keep the recordings local.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

from config import MIC_DEVICE, SAMPLE_RATE


DEFAULT_DATASET_DIR = Path(__file__).resolve().parent / "wakeword_dataset"
CLIP_SECONDS = 1.8

# Hard negatives are intentionally close to "Jarvis" plus ordinary speech.
NEGATIVE_PROMPTS = [
    "Jervis",
    "Jerry",
    "Jared",
    "Jar",
    "Java",
    "Hey",
    "Good morning",
    "How are you",
    "What's the weather",
    "What's the time",
    "Tell me a joke",
    "Open the browser",
    "Search Google",
    "Play some music",
    "Thank you",
]


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write mono int16 PCM WAV."""
    values = np.asarray(audio, dtype=np.int16).reshape(-1)

    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(values.tobytes())


def record_clip(
    *,
    device: int,
    sample_rate: int,
    seconds: float,
) -> np.ndarray:
    """Record one mono int16 clip from the configured microphone."""
    frames = max(1, round(sample_rate * seconds))

    # A brief delay after the cue keeps the beginning of the utterance
    # separate from the speaker prompt and gives the user a natural start.
    print("  Recording in 0.3s...", flush=True)
    time.sleep(0.30)

    audio = sd.rec(
        frames,
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        device=device,
    )
    sd.wait()

    return np.asarray(audio[:, 0], dtype=np.int16)


def rms(audio: np.ndarray) -> float:
    values = np.asarray(audio, dtype=np.float32)
    if values.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(np.square(values))))


def next_index(directory: Path, prefix: str) -> int:
    existing = []

    for path in directory.glob(f"{prefix}_*.wav"):
        try:
            existing.append(
                int(path.stem.rsplit("_", 1)[1])
            )
        except (ValueError, IndexError):
            continue

    return max(existing, default=0) + 1


def append_manifest(
    manifest_path: Path,
    *,
    path: Path,
    kind: str,
    phrase: str,
    audio: np.ndarray,
    sample_rate: int,
) -> None:
    if manifest_path.exists():
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            manifest = []
    else:
        manifest = []

    manifest.append(
        {
            "file": str(
                path.relative_to(manifest_path.parent)
            ),
            "kind": kind,
            "phrase": phrase,
            "sample_rate": sample_rate,
            "channels": 1,
            "duration_seconds": len(audio) / sample_rate,
            "rms": round(rms(audio), 2),
            "recorded_at": datetime.now().astimezone().isoformat(),
        }
    )

    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def record_set(
    *,
    dataset_dir: Path,
    kind: str,
    phrases: list[str],
    device: int,
    sample_rate: int,
    seconds: float,
) -> int:
    target_dir = dataset_dir / kind
    target_dir.mkdir(parents=True, exist_ok=True)

    prefix = "positive" if kind == "positive" else "negative"
    index = next_index(target_dir, prefix)
    manifest_path = dataset_dir / "manifest.json"

    for position, phrase in enumerate(phrases, start=1):
        print()
        print(f"[{position}/{len(phrases)}] Speak exactly:")
        print(f'  "{phrase}"')
        input("  Press Enter when ready...")

        audio = record_clip(
            device=device,
            sample_rate=sample_rate,
            seconds=seconds,
        )

        filename = f"{prefix}_{index:03d}.wav"
        path = target_dir / filename

        write_wav(
            path,
            audio,
            sample_rate,
        )

        append_manifest(
            manifest_path,
            path=path,
            kind=kind,
            phrase=phrase,
            audio=audio,
            sample_rate=sample_rate,
        )

        print(
            f"  Saved {path} "
            f"(RMS={rms(audio):.1f})"
        )

        index += 1

    return len(phrases)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record a local personalized JARVIS wake-word dataset."
        )
    )

    parser.add_argument(
        "--device",
        type=int,
        default=MIC_DEVICE,
        help=f"Input device index (default: {MIC_DEVICE})",
    )

    parser.add_argument(
        "--sample-rate",
        type=int,
        default=SAMPLE_RATE,
        help=f"Recording sample rate (default: {SAMPLE_RATE})",
    )

    parser.add_argument(
        "--seconds",
        type=float,
        default=CLIP_SECONDS,
        help=f"Seconds per clip (default: {CLIP_SECONDS})",
    )

    parser.add_argument(
        "--positive-count",
        type=int,
        default=20,
        help="Number of natural 'Jarvis' recordings (default: 20)",
    )

    parser.add_argument(
        "--negative-count",
        type=int,
        default=30,
        help="Number of negative recordings (default: 30)",
    )

    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help=f"Dataset directory (default: {DEFAULT_DATASET_DIR})",
    )

    parser.add_argument(
        "--negative-only",
        action="store_true",
        help="Record only negative samples.",
    )

    parser.add_argument(
        "--positive-only",
        action="store_true",
        help="Record only positive samples.",
    )

    args = parser.parse_args()

    if args.positive_only and args.negative_only:
        parser.error(
            "--positive-only and --negative-only cannot be used together"
        )

    if args.seconds <= 0:
        parser.error("--seconds must be greater than 0")

    if args.positive_count < 0 or args.negative_count < 0:
        parser.error("sample counts cannot be negative")

    if args.positive_count == 0 and args.negative_count == 0:
        parser.error(
            "at least one sample count must be greater than 0"
        )

    if args.positive_only:
        args.negative_count = 0

    if args.negative_only:
        args.positive_count = 0

    return args


def main() -> int:
    args = parse_args()

    dataset_dir = args.dataset_dir.resolve()
    dataset_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("========================================")
    print("JARVIS PERSONAL WAKE-WORD RECORDER")
    print("========================================")
    print(f"Device:       {args.device}")
    print(f"Sample rate:  {args.sample_rate}")
    print(f"Clip length:  {args.seconds:.2f}s")
    print(f"Dataset:      {dataset_dir}")
    print()
    print("Recordings stay local under wakeword_dataset/.")
    print("Do not upload or commit this directory.")
    print()

    if args.positive_count:
        print("POSITIVE SET")
        print(
            "Record the word naturally. Vary speed, pitch, distance, "
            "and emphasis without deliberately speaking louder."
        )

        positive_phrases = [
            "Jarvis"
        ] * args.positive_count

        record_set(
            dataset_dir=dataset_dir,
            kind="positive",
            phrases=positive_phrases,
            device=args.device,
            sample_rate=args.sample_rate,
            seconds=args.seconds,
        )

    if args.negative_count:
        print()
        print("NEGATIVE SET")
        print(
            "These must NOT be the wake word. Say the displayed phrase "
            "naturally in your normal voice."
        )

        phrases = [
            NEGATIVE_PROMPTS[index % len(NEGATIVE_PROMPTS)]
            for index in range(args.negative_count)
        ]

        record_set(
            dataset_dir=dataset_dir,
            kind="negative",
            phrases=phrases,
            device=args.device,
            sample_rate=args.sample_rate,
            seconds=args.seconds,
        )

    print()
    print("========================================")
    print("DATASET RECORDING COMPLETE")
    print("========================================")
    print(
        "Positive WAVs: "
        f"{len(list((dataset_dir / 'positive').glob('*.wav')))}"
    )
    print(
        "Negative WAVs: "
        f"{len(list((dataset_dir / 'negative').glob('*.wav')))}"
    )
    print(f"Manifest:      {dataset_dir / 'manifest.json'}")
    print()
    print(
        "Next step: inspect the dataset before training "
        "the personalized model."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
