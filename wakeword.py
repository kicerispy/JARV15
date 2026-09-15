import json
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
import onnxruntime as ort
import torch

from heed.audio import StreamingHighpass, log_mel


# ==================================================
# Paths
# ==================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "Jarvis" / "export" / "wake.onnx"
METADATA_PATH = BASE_DIR / "Jarvis" / "export" / "wake.json"


# ==================================================
# Microphone
# ==================================================

MIC_DEVICE = 1

SAMPLE_RATE = 16000

# 100 ms of audio per processing step.
CHUNK_SIZE = 1600


# ==================================================
# Load Heed metadata
# ==================================================

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Heed model not found:\n{MODEL_PATH}"
    )

if not METADATA_PATH.exists():
    raise FileNotFoundError(
        f"Heed metadata not found:\n{METADATA_PATH}"
    )


with open(
    METADATA_PATH,
    "r",
    encoding="utf-8",
) as f:
    META = json.load(f)


WAKE_THRESHOLD = float(
    META["threshold"]
)

METADATA_CONSECUTIVE_FRAMES = int(
    META["trigger"]["consecutive_frames"]
)

REFRACTORY_SECONDS = float(
    META["trigger"]["refractory_seconds"]
)

ENERGY_GATE_DBFS = float(
    META["energy_gate"]["rms_threshold_dbfs"]
)

VOICE_BAND_LO = float(
    META["energy_gate"]["voice_band_lo_hz"]
)

VOICE_BAND_HI = float(
    META["energy_gate"]["voice_band_hi_hz"]
)

VOICE_BAND_MIN_FRACTION = float(
    META["energy_gate"]["voice_band_min_fraction"]
)


# ==================================================
# Wake detection tuning
# ==================================================

# Keep a short history so the detector can recognize
# several strong predictions belonging to the same
# spoken wake word.
SCORE_HISTORY_SIZE = 5

# Require at least two real threshold hits.
MIN_STRONG_HITS = 2

# A single extremely confident prediction is enough.
STRONG_TRIGGER_THRESHOLD = max(
    0.88,
    WAKE_THRESHOLD + 0.12,
)

# Only slightly below the trained threshold.
# This is NOT allowed to trigger by itself.
SOFT_THRESHOLD = max(
    0.68,
    WAKE_THRESHOLD - 0.03,
)

# Require two moderately strong predictions when
# they are just below the main threshold.
MIN_SOFT_HITS = 2

# Don't print tiny probabilities.
DEBUG_PRINT_THRESHOLD = 0.30


# ==================================================
# Heed ONNX Runtime
# ==================================================

session = ort.InferenceSession(
    str(MODEL_PATH),
    providers=["CPUExecutionProvider"],
)

INPUT_NAME = session.get_inputs()[0].name
OUTPUT_NAME = session.get_outputs()[0].name


# ==================================================
# Streaming audio preprocessing
# ==================================================

preprocessor = StreamingHighpass(
    cutoff_hz=100.0,
    sample_rate=SAMPLE_RATE,
    order=8,
    apply_mains_notch=True,
)


# ==================================================
# Rolling audio buffer
# ==================================================

AUDIO_WINDOW_SAMPLES = 16000

audio_buffer = np.zeros(
    AUDIO_WINDOW_SAMPLES,
    dtype=np.float32,
)

samples_seen = 0


# ==================================================
# Wake state
# ==================================================

_last_wake_time = 0.0

_score_history = deque(
    maxlen=SCORE_HISTORY_SIZE
)


# ==================================================
# Helpers
# ==================================================

def reset_detector():
    global audio_buffer
    global samples_seen

    preprocessor.reset()

    audio_buffer.fill(0)

    samples_seen = 0

    _score_history.clear()


def get_rms_dbfs(audio):
    """
    Return RMS level in dBFS.
    """

    audio = np.asarray(
        audio,
        dtype=np.float32,
    )

    if audio.size == 0:
        return -120.0

    rms = float(
        np.sqrt(
            np.mean(
                np.square(audio)
            )
        )
    )

    if rms <= 1e-12:
        return -120.0

    return 20.0 * np.log10(rms)


def voice_band_fraction(audio):
    """
    Estimate how much spectral energy is present
    in the configured voice-frequency band.
    """

    audio = np.asarray(
        audio,
        dtype=np.float32,
    )

    if audio.size < 32:
        return 0.0

    window = np.hanning(
        len(audio)
    )

    spectrum = np.fft.rfft(
        audio * window
    )

    power = np.abs(spectrum) ** 2

    freqs = np.fft.rfftfreq(
        len(audio),
        d=1.0 / SAMPLE_RATE,
    )

    total_power = float(
        np.sum(power)
    )

    if total_power <= 1e-12:
        return 0.0

    mask = (
        (freqs >= VOICE_BAND_LO)
        &
        (freqs <= VOICE_BAND_HI)
    )

    voice_power = float(
        np.sum(power[mask])
    )

    return voice_power / total_power


def energy_gate_passes(audio):
    """
    Prevent the wake model from running on
    very quiet / non-voice audio.
    """

    rms_dbfs = get_rms_dbfs(audio)

    if rms_dbfs < ENERGY_GATE_DBFS:
        return False

    fraction = voice_band_fraction(
        audio
    )

    if fraction < VOICE_BAND_MIN_FRACTION:
        return False

    return True


def append_audio(audio):
    """
    Append filtered audio to the rolling
    one-second buffer.
    """

    global audio_buffer
    global samples_seen

    audio = np.asarray(
        audio,
        dtype=np.float32,
    )

    if audio.size == 0:
        return

    filtered = preprocessor(
        audio
    )

    filtered = np.asarray(
        filtered,
        dtype=np.float32,
    )

    n = len(filtered)

    if n >= AUDIO_WINDOW_SAMPLES:

        audio_buffer[:] = filtered[
            -AUDIO_WINDOW_SAMPLES:
        ]

        samples_seen = AUDIO_WINDOW_SAMPLES

    else:

        audio_buffer[:-n] = (
            audio_buffer[n:]
        )

        audio_buffer[-n:] = filtered

        samples_seen = min(
            AUDIO_WINDOW_SAMPLES,
            samples_seen + n,
        )


def get_wake_probability():
    """
    Run the Heed model against the current
    one-second rolling audio window.
    """

    if samples_seen < AUDIO_WINDOW_SAMPLES:
        return 0.0

    waveform = torch.from_numpy(
        audio_buffer.copy()
    )

    mel = log_mel(
        waveform,
        apply_cmn=True,
    )

    mel_np = (
        mel
        .detach()
        .cpu()
        .numpy()
        .astype(np.float32)
    )

    outputs = session.run(
        [OUTPUT_NAME],
        {
            INPUT_NAME: mel_np
        },
    )

    logit = float(
        np.asarray(
            outputs[0]
        ).reshape(-1)[0]
    )

    probability = 1.0 / (
        1.0 + np.exp(-logit)
    )

    return float(
        probability
    )


def wake_triggered(probability):
    """
    Decide whether the wake word was spoken.

    Trigger conditions:

    1. One extremely strong prediction.

    OR

    2. Two predictions at or above the trained
       threshold within the recent history.

    OR

    3. Two predictions close to the trained
       threshold within the recent history AND
       the current prediction is also moderately high.

    This avoids letting several weak predictions
    accidentally trigger JARVIS.
    """

    _score_history.append(
        probability
    )

    # --------------------------------------------------
    # 1. Very strong single-frame detection
    # --------------------------------------------------

    if probability >= STRONG_TRIGGER_THRESHOLD:

        print(
            "JARVIS: Strong wake prediction."
        )

        return True

    # --------------------------------------------------
    # 2. Multiple true-threshold hits
    # --------------------------------------------------

    strong_hits = sum(
        score >= WAKE_THRESHOLD
        for score in _score_history
    )

    if strong_hits >= MIN_STRONG_HITS:

        print(
            "JARVIS: Multiple strong wake predictions."
        )

        return True

    # --------------------------------------------------
    # 3. Near-threshold confirmation
    # --------------------------------------------------

    soft_hits = sum(
        score >= SOFT_THRESHOLD
        for score in _score_history
    )

    if (
        soft_hits >= MIN_SOFT_HITS
        and probability >= SOFT_THRESHOLD
    ):

        print(
            "JARVIS: Confirmed near-threshold wake predictions."
        )

        return True

    return False


# ==================================================
# Main wake listener
# ==================================================

def wait_for_wake_word():

    global _last_wake_time

    print(
        "JARVIS: Waiting for wake word..."
    )

    print(
        f"JARVIS: Custom Heed model loaded "
        f"(threshold={WAKE_THRESHOLD:.3f})"
    )

    print(
        f"JARVIS: Listening on microphone "
        f"device {MIC_DEVICE}"
    )

    print(
        f"JARVIS: Strong trigger threshold="
        f"{STRONG_TRIGGER_THRESHOLD:.3f}"
    )

    print(
        f"JARVIS: Soft threshold="
        f"{SOFT_THRESHOLD:.3f}"
    )

    print(
        f"JARVIS: Score history="
        f"{SCORE_HISTORY_SIZE}"
    )

    # --------------------------------------------------
    # Refractory period
    # --------------------------------------------------

    elapsed = (
        time.time()
        - _last_wake_time
    )

    if elapsed < REFRACTORY_SECONDS:

        time.sleep(
            REFRACTORY_SECONDS
            - elapsed
        )

    # --------------------------------------------------
    # Reset detector
    # --------------------------------------------------

    reset_detector()

    # --------------------------------------------------
    # Open microphone
    # --------------------------------------------------

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=CHUNK_SIZE,
        channels=1,
        dtype="float32",
        device=MIC_DEVICE,
    ) as stream:

        while True:

            audio, overflowed = (
                stream.read(CHUNK_SIZE)
            )

            if overflowed:
                continue

            audio = np.asarray(
                audio[:, 0],
                dtype=np.float32,
            )

            # --------------------------------------------------
            # Keep rolling audio continuous.
            # --------------------------------------------------

            append_audio(
                audio
            )

            # --------------------------------------------------
            # Energy gate
            # --------------------------------------------------

            if not energy_gate_passes(
                audio
            ):
                continue

            # --------------------------------------------------
            # Wake prediction
            # --------------------------------------------------

            probability = (
                get_wake_probability()
            )

            # --------------------------------------------------
            # Debug output
            # --------------------------------------------------

            if (
                probability
                >= DEBUG_PRINT_THRESHOLD
            ):

                print(
                    f"JARVIS score: "
                    f"{probability:.3f}"
                )

            # --------------------------------------------------
            # Wake decision
            # --------------------------------------------------

            if wake_triggered(
                probability
            ):

                print(
                    "================================"
                )

                print(
                    "JARVIS: WAKE WORD DETECTED"
                )

                print(
                    f"JARVIS: score="
                    f"{probability:.3f}"
                )

                print(
                    "JARVIS: recent scores="
                    f"{[round(x, 3) for x in _score_history]}"
                )

                print(
                    "================================"
                )

                _last_wake_time = (
                    time.time()
                )

                _score_history.clear()

                return True