"""
JARVIS hybrid voice activation engine.

Activation pipeline:
    microphone -> Silero VAD -> Heed wake candidate -> temporal fusion

The existing wakeword module remains the source of the Heed model and its
audio preprocessing. This module owns the higher-level activation decision so
wake-word tuning no longer has to be encoded as a single frame threshold.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Optional


# ============================================================
# ACTIVATION SETTINGS
# ============================================================

ACTIVATION_CHUNK_SIZE = 1600  # 100 ms at 16 kHz
VAD_WINDOW_SIZE = 512         # 32 ms at 16 kHz

# Silero VAD is used as a permissive speech gate, not as the wake decision.
# The official project notes that 0.5 is a reasonable generic speech threshold;
# we use a lower value here to avoid rejecting quiet wake-word attempts.
VAD_SPEECH_THRESHOLD = float(
    os.environ.get(
        "JARVIS_ACTIVATION_VAD_THRESHOLD",
        "0.35",
    )
)

# Candidate scores below this level are ignored by the temporal fusion stage.
HEED_CANDIDATE_THRESHOLD = float(
    os.environ.get(
        "JARVIS_ACTIVATION_CANDIDATE_THRESHOLD",
        "0.50",
    )
)

# Normal speech:
#   one very strong Heed frame can activate, or
#   multiple moderate/strong frames can activate together.
#
# A single-frame activation is reserved for very high confidence. Moderate
# candidates must arrive on consecutive frames, matching the exported Heed
# trigger behavior and preventing isolated spikes inside unrelated words.
NORMAL_SINGLE_TRIGGER = float(
    os.environ.get(
        "JARVIS_ACTIVATION_SINGLE_TRIGGER",
        "0.90",
    )
)

NORMAL_MULTI_TRIGGER = float(
    os.environ.get(
        "JARVIS_ACTIVATION_MULTI_TRIGGER",
        "0.62",
    )
)

# A second moderate hit must still have one stronger companion hit. This
# supports naturally spoken "Jarvis" patterns such as ~0.71 + ~0.71 while
# avoiding activation from a string of uniformly weak speech scores.
NORMAL_MULTI_SUPPORT_TRIGGER = float(
    os.environ.get(
        "JARVIS_ACTIVATION_MULTI_SUPPORT_TRIGGER",
        "0.68",
    )
)

NORMAL_SOFT_TRIGGER = float(
    os.environ.get(
        "JARVIS_ACTIVATION_SOFT_TRIGGER",
        "0.56",
    )
)

# Active background work is intentionally more conservative.
ACTIVE_TASK_SINGLE_TRIGGER = float(
    os.environ.get(
        "JARVIS_ACTIVATION_ACTIVE_TASK_TRIGGER",
        "0.92",
    )
)

# Keep confirmation tightly bound to one spoken wake-word event.
# At 100 ms per activation frame, six frames cover ~600 ms.
SCORE_WINDOW_FRAMES = int(
    os.environ.get(
        "JARVIS_ACTIVATION_SCORE_WINDOW",
        "6",
    )
)

MAX_SPEECH_EPISODE_SECONDS = float(
    os.environ.get(
        "JARVIS_ACTIVATION_EPISODE_SECONDS",
        "1.80",
    )
)

SPEECH_RESET_SECONDS = float(
    os.environ.get(
        "JARVIS_ACTIVATION_SILENCE_RESET_SECONDS",
        "0.30",
    )
)

# Require speech support for activation. This protects against strong
# wake-model scores caused by non-speech audio or stale rolling context.
MIN_SPEECH_SUPPORT = float(
    os.environ.get(
        "JARVIS_ACTIVATION_MIN_SPEECH_SUPPORT",
        "0.45",
    )
)

DEBUG_ACTIVATION = (
    os.environ.get(
        "JARVIS_ACTIVATION_DEBUG",
        "0",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

_runtime_cache: Optional[Any] = None



# ============================================================
# DATA TYPES
# ============================================================

@dataclass(frozen=True)
class ActivationDecision:
    triggered: bool
    reason: str
    peak_score: float
    top_scores: tuple[float, ...]


@dataclass
class ActivationRuntime:
    wakeword: Any
    vad_model: Any
    vad_available: bool


# ============================================================
# PURE TEMPORAL FUSION
# ============================================================

def _speech_support(
    speech_scores: list[float],
) -> float:
    """Return the fraction of recent chunks containing clear speech."""
    if not speech_scores:
        return 0.0

    supported = sum(
        score >= VAD_SPEECH_THRESHOLD
        for score in speech_scores
    )

    return supported / len(speech_scores)


def evaluate_wake_scores(
    scores: list[float] | tuple[float, ...],
    speech_scores: list[float] | tuple[float, ...],
    *,
    active_task: bool = False,
) -> ActivationDecision:
    """
    Fuse a short sequence of Heed scores with speech evidence.

    This function is intentionally deterministic so it can be unit-tested
    without loading any audio models.
    """
    recent_scores = [
        float(score)
        for score in scores
        if float(score) >= HEED_CANDIDATE_THRESHOLD
    ]

    recent_speech = [
        float(score)
        for score in speech_scores
    ]

    if not recent_scores:
        return ActivationDecision(
            False,
            "no wake candidate",
            0.0,
            (),
        )

    peak = max(recent_scores)
    speech_support = _speech_support(recent_speech)

    if speech_support < MIN_SPEECH_SUPPORT:
        return ActivationDecision(
            False,
            "insufficient speech support",
            peak,
            tuple(
                sorted(
                    recent_scores,
                    reverse=True,
                )[:3]
            ),
        )

    top_scores = tuple(
        sorted(
            recent_scores,
            reverse=True,
        )[:3]
    )

    if active_task:
        if peak >= ACTIVE_TASK_SINGLE_TRIGGER:
            return ActivationDecision(
                True,
                "strong active-task wake",
                peak,
                top_scores,
            )

        return ActivationDecision(
            False,
            "active-task confidence insufficient",
            peak,
            top_scores,
        )

    if peak >= NORMAL_SINGLE_TRIGGER:
        return ActivationDecision(
            True,
            "strong single-frame wake",
            peak,
            top_scores,
        )

    # Require consecutive moderate/strong predictions. An isolated high
    # score such as 0.811 in a hard-negative "Jared" recording should not
    # activate JARVIS.
    for index in range(len(recent_scores) - 1):
        first = recent_scores[index]
        second = recent_scores[index + 1]

        if (
            first >= NORMAL_MULTI_TRIGGER
            and second >= NORMAL_MULTI_TRIGGER
            and max(first, second) >= NORMAL_MULTI_SUPPORT_TRIGGER
            and (first + second) / 2.0 >= NORMAL_MULTI_TRIGGER
        ):
            return ActivationDecision(
                True,
                "consecutive multi-frame wake confirmation",
                peak,
                (
                    max(first, second),
                    min(first, second),
                ),
            )

    # A softer path remains available, but all three moderate predictions
    # must be consecutive so a scattered sequence cannot trigger.
    for index in range(len(recent_scores) - 2):
        window = recent_scores[index:index + 3]

        if (
            all(
                score >= NORMAL_SOFT_TRIGGER
                for score in window
            )
            and sum(window) / 3.0 >= 0.59
            and max(window) >= 0.64
        ):
            return ActivationDecision(
                True,
                "consecutive soft multi-frame wake confirmation",
                peak,
                tuple(
                    sorted(
                        window,
                        reverse=True,
                    )
                ),
            )

    return ActivationDecision(
        False,
        "wake candidate not yet confirmed",
        peak,
        top_scores,
    )


# ============================================================
# SILERO VAD
# ============================================================

def _load_vad_model() -> tuple[Any, bool]:
    """
    Load the packaged Silero VAD ONNX model.

    VAD is optional at runtime so JARVIS can still operate with its existing
    energy/voice-band gate if the dependency is not installed yet.
    """
    try:
        from silero_vad import load_silero_vad

        model = load_silero_vad(
            onnx=True,
            opset_version=16,
        )
        model.reset_states()

        return model, True

    except Exception as exc:
        print(
            "JARVIS activation: Silero VAD unavailable; "
            f"using existing audio gate ({exc})"
        )
        return None, False


def _silero_speech_probability(
    vad_model: Any,
    audio: Any,
) -> float:
    """Run stateful Silero VAD over one 100 ms microphone chunk."""
    import numpy as np
    import torch

    values = np.asarray(
        audio,
        dtype=np.float32,
    ).reshape(-1)

    probabilities = []

    # Silero's 16 kHz streaming model uses 512-sample windows.
    for start in range(
        0,
        len(values) - VAD_WINDOW_SIZE + 1,
        VAD_WINDOW_SIZE,
    ):
        chunk = values[
            start : start + VAD_WINDOW_SIZE
        ]

        tensor = torch.from_numpy(
            np.ascontiguousarray(chunk)
        )

        try:
            probability = float(
                vad_model(
                    tensor,
                    16000,
                ).item()
            )
        except Exception:
            probability = 0.0

        probabilities.append(probability)

    return max(
        probabilities,
        default=0.0,
    )


# ============================================================
# RUNTIME
# ============================================================

def _create_runtime() -> ActivationRuntime:
    global _runtime_cache

    if _runtime_cache is not None:
        return _runtime_cache

    import wakeword

    vad_model, vad_available = _load_vad_model()

    if vad_available:
        print(
            "JARVIS activation: "
            "Silero VAD + Heed temporal fusion ready."
        )
    else:
        print(
            "JARVIS activation: "
            "Heed temporal fusion ready."
        )

    _runtime_cache = ActivationRuntime(
        wakeword=wakeword,
        vad_model=vad_model,
        vad_available=vad_available,
    )

    return _runtime_cache


def _speech_is_present(
    runtime: ActivationRuntime,
    audio: Any,
) -> tuple[float, bool]:
    """
    Return (speech_probability, gate_passed).

    Silero is the primary speech gate. The existing Heed energy/voice-band
    gate remains a fallback and a secondary sanity check.
    """
    energy_passes = runtime.wakeword.energy_gate_passes(
        audio
    )

    if runtime.vad_available:
        speech_probability = _silero_speech_probability(
            runtime.vad_model,
            audio,
        )

        # VAD is the primary speech decision. The existing calibrated
        # energy/voice-band gate is a rescue path for quiet consonants or
        # short VAD confidence dips so activation does not become brittle.
        gate_passed = (
            speech_probability >= VAD_SPEECH_THRESHOLD
            or energy_passes
        )

        return (
            max(
                speech_probability,
                1.0 if energy_passes else 0.0,
            ),
            gate_passed,
        )

    return (
        1.0 if energy_passes else 0.0,
        energy_passes,
    )


# ============================================================
# MAIN ACTIVATION LOOP
# ============================================================

def wait_for_activation(
    interrupt_event: Optional[Any] = None,
    active_task: bool = False,
) -> bool:
    """
    Wait until the hybrid activation engine confirms a wake event.

    Returns True only after VAD + Heed temporal fusion agree sufficiently.
    """
    import numpy as np
    import sounddevice as sd

    runtime = _create_runtime()
    wakeword = runtime.wakeword

    print(
        "JARVIS: Waiting for wake word..."
    )
    print(
        "JARVIS activation: "
        f"VAD={'Silero' if runtime.vad_available else 'energy'}"
    )
    print(
        "JARVIS activation: "
        f"Heed candidate={HEED_CANDIDATE_THRESHOLD:.3f} "
        f"single={NORMAL_SINGLE_TRIGGER:.3f} "
        f"multi={NORMAL_MULTI_TRIGGER:.3f}"
    )

    if active_task:
        print(
            "JARVIS activation: "
            f"active-task={ACTIVE_TASK_SINGLE_TRIGGER:.3f}"
        )

    wakeword.reset_detector()

    score_history: Deque[float] = deque(
        maxlen=SCORE_WINDOW_FRAMES
    )
    speech_history: Deque[float] = deque(
        maxlen=SCORE_WINDOW_FRAMES
    )

    speech_episode_started = None
    silence_started = None

    try:
        if (
            runtime.vad_available
            and runtime.vad_model is not None
        ):
            runtime.vad_model.reset_states()

        with sd.InputStream(
            samplerate=16000,
            blocksize=ACTIVATION_CHUNK_SIZE,
            channels=1,
            dtype="float32",
            device=wakeword.MIC_DEVICE,
        ) as stream:

            while True:
                if (
                    interrupt_event is not None
                    and interrupt_event.is_set()
                ):
                    return False

                audio, overflowed = stream.read(
                    ACTIVATION_CHUNK_SIZE
                )

                if overflowed:
                    continue

                audio = np.asarray(
                    audio[:, 0],
                    dtype=np.float32,
                )

                # Keep Heed's rolling audio buffer continuous even while VAD
                # is evaluating the microphone signal.
                wakeword.append_audio(audio)

                speech_probability, speech_present = (
                    _speech_is_present(
                        runtime,
                        audio,
                    )
                )

                if not speech_present:
                    if silence_started is None:
                        silence_started = time.monotonic()

                    if (
                        time.monotonic()
                        - silence_started
                        >= SPEECH_RESET_SECONDS
                    ):
                        score_history.clear()
                        speech_history.clear()
                        speech_episode_started = None

                    continue

                silence_started = None

                if speech_episode_started is None:
                    speech_episode_started = time.monotonic()

                speech_episode_age = (
                    time.monotonic()
                    - speech_episode_started
                )

                if speech_episode_age > MAX_SPEECH_EPISODE_SECONDS:
                    # Do not keep hunting for a wake word deep inside a long
                    # sentence. Re-arm after a genuine silence reset.
                    score_history.clear()
                    speech_history.clear()

                    if DEBUG_ACTIVATION:
                        print(
                            "JARVIS activation: wake candidate window expired; "
                            "waiting for speech reset."
                        )

                    continue

                probability = wakeword.get_wake_probability()

                score_history.append(
                    probability
                )
                speech_history.append(
                    speech_probability
                )

                if DEBUG_ACTIVATION and (
                    probability >= 0.30
                    or speech_probability >= 0.50
                ):
                    print(
                        "JARVIS activation: "
                        f"speech={speech_probability:.3f} "
                        f"heed={probability:.3f} "
                        f"scores={[round(x, 3) for x in score_history]}"
                    )

                decision = evaluate_wake_scores(
                    list(score_history),
                    list(speech_history),
                    active_task=active_task,
                )

                if decision.triggered:
                    print(
                        "================================"
                    )
                    print(
                        "JARVIS: WAKE WORD DETECTED"
                    )
                    print(
                        "JARVIS activation: "
                        f"reason={decision.reason} "
                        f"peak={decision.peak_score:.3f}"
                    )
                    print(
                        "JARVIS activation: "
                        f"top_scores={list(decision.top_scores)}"
                    )
                    print(
                        "================================"
                    )

                    wakeword._last_wake_time = time.time()
                    score_history.clear()
                    speech_history.clear()

                    return True

    except Exception as exc:
        print(
            "JARVIS activation error:",
            exc,
        )
        return False
