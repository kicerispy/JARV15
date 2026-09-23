import os
import threading
import collections
import time


# ============================================================
# CUDA DLL SETUP
# ============================================================

try:
    import torch

    torch_lib = os.path.join(
        os.path.dirname(torch.__file__),
        "lib"
    )

    if os.path.isdir(torch_lib):

        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(torch_lib)

        os.environ["PATH"] = (
            torch_lib
            + os.pathsep
            + os.environ.get("PATH", "")
        )

        print(
            "JARVIS TTS: Added Torch DLL directory:"
        )

        print(
            torch_lib
        )

except Exception as e:

    print(
        "JARVIS TTS: CUDA DLL setup warning:",
        e
    )


# ============================================================
# IMPORTS
# ============================================================

import numpy as np
import sounddevice as sd
import onnxruntime as ort

from scipy import signal

from piper import PiperVoice, SynthesisConfig

from config import (
    OUTPUT_GAIN as CONFIG_OUTPUT_GAIN,
    PITCH_RATIO as CONFIG_PITCH_RATIO,
    TTS_LENGTH_SCALE,
    TTS_NOISE_SCALE,
    TTS_NOISE_W,
    VOICE_MODEL_PATH,
    HIGH_GAIN_DB as CONFIG_HIGH_GAIN_DB,
    LOW_SHELF_GAIN_DB as CONFIG_LOW_SHELF_GAIN_DB,
    PRESENCE_GAIN_DB as CONFIG_PRESENCE_GAIN_DB,
)

from echo_canceller import create_echo_canceller


# ============================================================
# DEVICE / AUDIO SETTINGS
# ============================================================

OUTPUT_DEVICE = 5
MIC_DEVICE = 1

SAMPLE_RATE = 16000


VOICE_MODEL = os.path.expanduser(str(VOICE_MODEL_PATH))


# ============================================================
# PIPER VOICE SETTINGS
# ============================================================

# Higher = slower.

LENGTH_SCALE = TTS_LENGTH_SCALE

NOISE_SCALE = TTS_NOISE_SCALE

NOISE_W_SCALE = TTS_NOISE_W


# ============================================================
# JARVIS AUDIO CHARACTER
# ============================================================

# Slightly lower pitch.

PITCH_RATIO = CONFIG_PITCH_RATIO


# Warm low frequencies.

LOW_SHELF_GAIN_DB = CONFIG_LOW_SHELF_GAIN_DB


# Slightly reduce upper-mid harshness.

PRESENCE_GAIN_DB = CONFIG_PRESENCE_GAIN_DB


# Slightly soften highs.

HIGH_GAIN_DB = CONFIG_HIGH_GAIN_DB


# Gentle compression.

COMP_THRESHOLD = 0.55

COMP_RATIO = 2.2


# Final volume.

OUTPUT_GAIN = CONFIG_OUTPUT_GAIN


# ============================================================
# BARGE-IN SETTINGS
#
# Based on your actual measurements:
#
# Silence:
#   Average ~59.5 RMS
#   Maximum ~76.4 RMS
#
# JARVIS playback through microphone:
#   Average ~61.9 RMS
#   Maximum ~85.2 RMS
#
# Your voice:
#   Average ~349.7 RMS
#   Maximum ~985.5 RMS
# ============================================================

INTERRUPT_THRESHOLD = 220

# 4 x 1024 samples at 16 kHz ≈ 256 ms.

INTERRUPT_CHUNKS = 5

# Ignore startup transient when playback begins.

INTERRUPT_GRACE_SECONDS = 0.40


# ------------------------------------------------------------
# Keep audio before speech detection.
# ------------------------------------------------------------

PREBUFFER_SECONDS = 0.35

PREBUFFER_CHUNKS = max(
    1,
    int(
        PREBUFFER_SECONDS
        * SAMPLE_RATE
        / 1024
    )
)


# ============================================================
# BARGE-IN STATE
# ============================================================

# This event ONLY means:
# "stop the microphone monitor."

_monitor_stop_event = threading.Event()


# This event ONLY means:
# "the user actually interrupted JARVIS."

_interrupted_event = threading.Event()


# Captured microphone audio from the interruption.

_interrupted_audio = None

_interrupt_lock = threading.Lock()


# ============================================================
# TTS LOCK
# ============================================================

_speak_lock = threading.Lock()

# Suppress accidental back-to-back duplicate utterances caused by concurrent
# task/completion delivery paths. Legitimate repeated speech after this short
# window is still allowed.
_DUPLICATE_SPEECH_WINDOW = 5.0
_duplicate_speech_lock = threading.Lock()
_last_spoken_key = ""
_last_spoken_at = 0.0

_echo_canceller = create_echo_canceller()

# Playback reference for speaker-echo detection. The exact processed TTS waveform
# is retained so the microphone monitor can distinguish room/speaker echo from
# independently spoken user audio.
_playback_reference = None
_playback_reference_started_at = 0.0
_playback_reference_lock = threading.Lock()

ECHO_CORRELATION_THRESHOLD = 0.42
ECHO_RESIDUAL_RATIO_THRESHOLD = 0.86
ECHO_SEARCH_MIN_DELAY_SECONDS = 0.00
ECHO_SEARCH_MAX_DELAY_SECONDS = 0.75
ECHO_SEARCH_STEP_SECONDS = 0.01

# Evaluate a short rolling window so one imperfect echo match cannot
# accidentally trigger an interruption. Six 1024-sample chunks at 16 kHz
# cover ~384 ms.
BARGE_IN_WINDOW_CHUNKS = 6
MAX_ECHO_CHUNKS_IN_WINDOW = 1
DEBUG_BARGE_IN = False

def _speech_dedup_key(text):
    """Build a key from the exact text after JARVIS speech normalization."""
    try:
        from response_pipeline import clean_for_speech
        cleaned = clean_for_speech(str(text or ""))
    except Exception:
        cleaned = str(text or "")

    return " ".join(
        str(cleaned or "").strip().split()
    ).casefold()


# ============================================================
# LOAD PIPER
# ============================================================

print(
    "JARVIS TTS: Loading Piper voice..."
)


try:

    if not os.path.exists(
        VOICE_MODEL
    ):

        raise FileNotFoundError(
            f"Piper voice model not found:\n"
            f"{VOICE_MODEL}"
        )

    try:
        _available_onnx_providers = (
            ort.get_available_providers()
        )
    except Exception:
        _available_onnx_providers = []

    _using_cuda = (
        "CUDAExecutionProvider"
        in _available_onnx_providers
    )

    print(
        "JARVIS TTS: ONNX Runtime providers = "
        + ", ".join(_available_onnx_providers or ["unknown"])
    )

    _voice = PiperVoice.load(
        VOICE_MODEL,
        use_cuda=_using_cuda
    )

    print(
        "JARVIS TTS: Piper inference provider = "
        + ("CUDA" if _using_cuda else "CPU")
    )


except Exception as e:

    print(
        "JARVIS TTS: Piper load failed:"
    )

    print(
        e
    )

    _voice = None
    _using_cuda = False


# ============================================================
# PITCH SHIFT
# ============================================================

def pitch_shift(
    audio,
    sample_rate,
    ratio
):

    if len(audio) < 32:
        return audio


    new_length = max(
        1,
        int(
            len(audio)
            / ratio
        )
    )


    shifted = signal.resample(
        audio,
        new_length
    )


    restored = signal.resample(
        shifted,
        len(audio)
    )


    return restored.astype(
        np.float32
    )


# ============================================================
# FILTER HELPER
# ============================================================

def apply_filter(
    audio,
    sos
):

    if len(audio) < 16:
        return audio


    return signal.sosfilt(
        sos,
        audio
    ).astype(
        np.float32
    )


# ============================================================
# JARVIS EQ
# ============================================================

def apply_jarvis_eq(
    audio,
    sample_rate
):

    # --------------------------------------------------------
    # Low-end warmth
    # --------------------------------------------------------

    low_shelf = signal.butter(
        2,
        180,
        btype="lowpass",
        fs=sample_rate,
        output="sos"
    )


    low = apply_filter(
        audio,
        low_shelf
    )


    low_gain = (
        10 ** (
            LOW_SHELF_GAIN_DB
            / 20.0
        )
        - 1.0
    )


    audio = (
        audio
        + low * low_gain
    )


    # --------------------------------------------------------
    # Presence reduction
    # --------------------------------------------------------

    presence = signal.butter(
        2,
        [1800, 3800],
        btype="bandpass",
        fs=sample_rate,
        output="sos"
    )


    presence_band = apply_filter(
        audio,
        presence
    )


    presence_gain = (
        10 ** (
            PRESENCE_GAIN_DB
            / 20.0
        )
    )


    audio = (
        audio
        - presence_band
        + presence_band * presence_gain
    )


    # --------------------------------------------------------
    # High-frequency reduction
    # --------------------------------------------------------

    highs = signal.butter(
        2,
        5200,
        btype="highpass",
        fs=sample_rate,
        output="sos"
    )


    high_band = apply_filter(
        audio,
        highs
    )


    high_gain = (
        10 ** (
            HIGH_GAIN_DB
            / 20.0
        )
    )


    audio = (
        audio
        - high_band
        + high_band * high_gain
    )


    return audio.astype(
        np.float32
    )


# ============================================================
# COMPRESSOR
# ============================================================

def compress_audio(
    audio,
    threshold=0.55,
    ratio=2.2
):

    abs_audio = np.abs(
        audio
    )

    sign = np.sign(
        audio
    )


    compressed = np.where(
        abs_audio > threshold,
        threshold
        + (
            (abs_audio - threshold)
            / ratio
        ),
        abs_audio
    )


    return (
        sign
        * compressed
    ).astype(
        np.float32
    )


# ============================================================
# NORMALIZE
# ============================================================

def normalize_audio(
    audio,
    target=0.86
):

    peak = np.max(
        np.abs(audio)
    )


    if peak <= 0:
        return audio


    return (
        audio
        * (
            target
            / peak
        )
    ).astype(
        np.float32
    )


# ============================================================
# COMPLETE AUDIO PROCESSING
# ============================================================

def process_audio(
    audio,
    sample_rate
):

    audio = audio.astype(
        np.float32
    )


    peak = np.max(
        np.abs(audio)
    )


    if peak > 1.0:

        audio /= 32768.0


    # --------------------------------------------------------
    # Small fade to prevent clicks.
    # --------------------------------------------------------

    fade_samples = min(
        int(
            sample_rate
            * 0.006
        ),
        len(audio) // 2
    )


    if fade_samples > 0:

        fade = np.linspace(
            0.0,
            1.0,
            fade_samples,
            dtype=np.float32
        )


        audio[
            :fade_samples
        ] *= fade


        audio[
            -fade_samples:
        ] *= fade[::-1]


    # --------------------------------------------------------
    # Lower pitch slightly.
    # --------------------------------------------------------

    audio = pitch_shift(
        audio,
        sample_rate,
        PITCH_RATIO
    )


    # --------------------------------------------------------
    # EQ.
    # --------------------------------------------------------

    audio = apply_jarvis_eq(
        audio,
        sample_rate
    )


    # --------------------------------------------------------
    # Compression.
    # --------------------------------------------------------

    audio = compress_audio(
        audio,
        COMP_THRESHOLD,
        COMP_RATIO
    )


    # --------------------------------------------------------
    # Normalize.
    # --------------------------------------------------------

    audio = normalize_audio(
        audio,
        0.86
    )


    # --------------------------------------------------------
    # Final output gain.
    # --------------------------------------------------------

    audio *= OUTPUT_GAIN


    return np.clip(
        audio,
        -1.0,
        1.0
    ).astype(
        np.float32
    )


# ============================================================
# MICROPHONE RMS
# ============================================================

def _get_volume(
    audio
):

    audio = np.asarray(
        audio,
        dtype=np.int16
    )


    if len(audio) == 0:
        return 0.0


    return float(
        np.sqrt(
            np.mean(
                audio.astype(
                    np.float32
                ) ** 2
            )
        )
    )



# ============================================================
# PLAYBACK REFERENCE CHUNK
# ============================================================
def _get_playback_reference_chunk(length):
    with _playback_reference_lock:
        reference = _playback_reference
        started_at = _playback_reference_started_at

    if reference is None or started_at <= 0:
        return np.zeros(length, dtype=np.int16)

    elapsed = max(
        0.0,
        time.monotonic() - started_at,
    )

    start = int(elapsed * SAMPLE_RATE)
    end = start + length

    if start >= len(reference):
        return np.zeros(length, dtype=np.int16)

    chunk = reference[
        start : min(end, len(reference))
    ]

    if len(chunk) < length:
        chunk = np.pad(
            chunk,
            (0, length - len(chunk)),
        )

    peak = (
        float(np.max(np.abs(chunk)))
        if len(chunk)
        else 0.0
    )

    if peak <= 1.5:
        chunk = (
            chunk.astype(np.float32)
            * 32767.0
        )

    return np.clip(
        chunk,
        -32768,
        32767,
    ).astype(np.int16)


# ============================================================
# SPEAKER ECHO MATCHING
# ============================================================
def _prepare_playback_reference(audio, sample_rate):
    """Convert the exact playback waveform to the microphone sample rate."""
    try:
        if audio is None or len(audio) < 64:
            return None

        reference = np.asarray(audio, dtype=np.float32).reshape(-1)

        if sample_rate != SAMPLE_RATE:
            reference = signal.resample_poly(
                reference,
                SAMPLE_RATE,
                int(sample_rate),
            ).astype(np.float32)

        return reference
    except Exception as e:
        print("JARVIS TTS: Echo reference preparation warning:", e)
        return None


def _echo_match(audio):
    """
    Compare a microphone chunk against nearby delayed portions of the exact
    JARVIS playback waveform.

    Returns:
        (correlation, residual_ratio)
    """
    with _playback_reference_lock:
        reference = _playback_reference
        started_at = _playback_reference_started_at

    if reference is None or len(reference) < 1024 or started_at <= 0:
        return 0.0, 1.0

    mic = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(mic) < 256:
        return 0.0, 1.0

    mic = mic - float(np.mean(mic))
    mic_norm = float(np.linalg.norm(mic))
    if mic_norm < 1.0:
        return 0.0, 1.0

    elapsed = time.monotonic() - started_at
    if elapsed <= 0:
        return 0.0, 1.0

    best_corr = 0.0
    best_residual_ratio = 1.0

    min_delay = ECHO_SEARCH_MIN_DELAY_SECONDS
    max_delay = ECHO_SEARCH_MAX_DELAY_SECONDS
    step = ECHO_SEARCH_STEP_SECONDS

    delay = min_delay
    while delay <= max_delay:
        center = int(
            (elapsed - delay)
            * SAMPLE_RATE
        )

        start = center
        end = start + len(mic)

        if start < 0 or end > len(reference):
            delay += step
            continue

        ref = reference[start:end].copy()
        ref -= float(np.mean(ref))

        ref_norm = float(np.linalg.norm(ref))
        if ref_norm < 1e-6:
            delay += step
            continue

        corr = float(
            np.dot(mic, ref)
            / (
                mic_norm
                * ref_norm
            )
        )

        if corr > best_corr:
            gain = float(
                np.dot(mic, ref)
                / max(
                    np.dot(ref, ref),
                    1e-9
                )
            )

            residual = (
                mic
                - gain * ref
            )

            residual_ratio = float(
                np.linalg.norm(residual)
                / mic_norm
            )

            best_corr = corr
            best_residual_ratio = residual_ratio

        delay += step

    return best_corr, best_residual_ratio


# ============================================================
# MICROPHONE BARGE-IN MONITOR
# ============================================================

def _monitor_microphone():

    global _interrupted_audio


    ring_buffer = collections.deque(
        maxlen=PREBUFFER_CHUNKS
    )


    consecutive_loud = 0

    # Rolling evidence for barge-in decisions. A user interruption should
    # contain sustained loud audio with very little resemblance to JARVIS'
    # known playback waveform.
    loud_window = collections.deque(
        maxlen=BARGE_IN_WINDOW_CHUNKS
    )
    echo_window = collections.deque(
        maxlen=BARGE_IN_WINDOW_CHUNKS
    )


    monitor_start = time.time()


    try:

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=1024,
            channels=1,
            dtype="int16",
            device=MIC_DEVICE
        ) as stream:


            while not _monitor_stop_event.is_set():

                audio, overflowed = (
                    stream.read(1024)
                )


                if overflowed:
                    continue


                audio = np.asarray(
                    audio[:, 0],
                    dtype=np.int16
                )


                # Keep recent audio for Whisper.

                ring_buffer.append(
                    audio.copy()
                )


                # -----------------------------------------
                # Ignore initial startup period.
                # -----------------------------------------

                if (
                    time.time()
                    - monitor_start
                    < INTERRUPT_GRACE_SECONDS
                ):

                    continue


                raw_microphone_audio = audio.copy()

                # Feed the exact processed TTS render to WebRTC AEC3 so the
                # monitor works from a cleaned microphone signal. The existing
                # waveform matcher remains available as a fallback signal.
                if _echo_canceller is not None:
                    speaker_reference = _get_playback_reference_chunk(
                        len(audio)
                    )

                    try:
                        audio = _echo_canceller.process(
                            audio,
                            speaker_reference,
                        )
                    except Exception as exc:
                        print(
                            "JARVIS AEC: processing warning:",
                            exc,
                        )
                        audio = raw_microphone_audio

                volume = _get_volume(
                    audio
                )

                echo_correlation, echo_residual_ratio = (
                    _echo_match(raw_microphone_audio)
                )

                # Speaker echo is compared against the exact processed TTS
                # waveform with a broad delay search. Do not use a fixed
                # microphone-volume ceiling: room acoustics and speaker
                # placement can make the echoed signal substantially louder
                # than the earlier calibration.
                likely_echo = (
                    echo_correlation
                    >= ECHO_CORRELATION_THRESHOLD
                    and echo_residual_ratio
                    <= ECHO_RESIDUAL_RATIO_THRESHOLD
                )

                if likely_echo and volume >= INTERRUPT_THRESHOLD:
                    if DEBUG_BARGE_IN:
                        print(
                            "JARVIS: Speaker echo candidate suppressed "
                            f"(volume={volume:.1f}, "
                            f"corr={echo_correlation:.2f}, "
                            f"residual={echo_residual_ratio:.2f})"
                        )

                loud_window.append(
                    volume >= INTERRUPT_THRESHOLD
                )
                echo_window.append(
                    likely_echo
                )

                # An echo-like chunk cannot contribute to sustained
                # interruption evidence. A rolling window tolerates an
                # occasional correlation miss without allowing a pure speaker
                # echo stream to trigger playback cancellation.
                if likely_echo:
                    consecutive_loud = 0
                    continue

                # -----------------------------------------
                # Sustained speech evidence.
                # -----------------------------------------

                if (
                    volume
                    >= INTERRUPT_THRESHOLD
                ):

                    consecutive_loud += 1

                else:

                    consecutive_loud = 0


                # -----------------------------------------
                # Real user interruption.
                # -----------------------------------------

                enough_loud = (
                    len(loud_window)
                    >= BARGE_IN_WINDOW_CHUNKS
                    and sum(loud_window)
                    >= INTERRUPT_CHUNKS
                )

                mostly_non_echo = (
                    len(echo_window)
                    >= BARGE_IN_WINDOW_CHUNKS
                    and sum(echo_window)
                    <= MAX_ECHO_CHUNKS_IN_WINDOW
                )

                if (
                    enough_loud
                    and mostly_non_echo
                ):

                    buffered = list(
                        ring_buffer
                    )


                    if buffered:

                        captured_audio = (
                            np.concatenate(
                                buffered
                            )
                        )

                    else:

                        captured_audio = (
                            audio.copy()
                        )


                    with _interrupt_lock:

                        _interrupted_audio = (
                            captured_audio
                        )


                    # IMPORTANT:
                    #
                    # This is the ONLY place where the
                    # interrupted event is set.

                    _interrupted_event.set()


                    print(
                        "\nJARVIS: "
                        "Speech detected — interrupting."
                    )


                    break


    except Exception as e:

        print(
            "JARVIS barge-in monitor error:",
            e
        )


# ============================================================
# INTERRUPTION API
# ============================================================

def was_interrupted():

    return _interrupted_event.is_set()


def get_interrupted_audio():

    global _interrupted_audio


    with _interrupt_lock:

        audio = _interrupted_audio

        _interrupted_audio = None


    return audio


def clear_interruption():

    global _interrupted_audio


    _interrupted_event.clear()

    _monitor_stop_event.clear()


    with _interrupt_lock:

        _interrupted_audio = None


# ============================================================
# SPEAK
# ============================================================

def speak(text):

    t_total_start = time.perf_counter()

    if text is None:
        return False


    text = str(
        text
    ).strip()


    if not text:
        return False

    # Final TTS-layer safety net: the task system may deliver the same final
    # message through two completion paths during a race. Suppress only an
    # identical utterance arriving immediately after the previous one.
    now = time.monotonic()
    speech_key = _speech_dedup_key(text)
    global _last_spoken_key, _last_spoken_at
    with _duplicate_speech_lock:
        if (
            speech_key == _last_spoken_key
            and now - _last_spoken_at < _DUPLICATE_SPEECH_WINDOW
        ):
            print(
                f"JARVIS TTS: Suppressed duplicate utterance: {text}"
            )
            return False

        _last_spoken_key = speech_key
        _last_spoken_at = now

    print(
        f"JARVIS TTS: {text}"
    )


    if _voice is None:

        print(
            "JARVIS TTS: "
            "Voice engine unavailable."
        )

        return False


    with _speak_lock:

        # ----------------------------------------------------
        # Reset both events before every utterance.
        # ----------------------------------------------------

        _interrupted_event.clear()
        _monitor_stop_event.clear()

        if _echo_canceller is not None:
            try:
                _echo_canceller.reset()
            except Exception as exc:
                print(
                    "JARVIS AEC: reset warning:",
                    exc,
                )


        with _interrupt_lock:

            global _interrupted_audio

            _interrupted_audio = None


        try:

            # ------------------------------------------------
            # Piper configuration
            # ------------------------------------------------

            config = SynthesisConfig(
                length_scale=LENGTH_SCALE,
                noise_scale=NOISE_SCALE,
                noise_w_scale=NOISE_W_SCALE,
            )


            # ------------------------------------------------
            # Synthesize
            # ------------------------------------------------

            t_synth_start = time.perf_counter()

            audio_chunks = []

            sample_rate = None


            for chunk in _voice.synthesize(
                text,
                config
            ):

                if sample_rate is None:

                    sample_rate = (
                        chunk.sample_rate
                    )


                audio_chunks.append(
                    chunk.audio_int16_bytes
                )

            t_synth_end = time.perf_counter()


            if not audio_chunks:

                print(
                    "JARVIS TTS: "
                    "No audio generated."
                )

                return False


            # ------------------------------------------------
            # Convert Piper output
            # ------------------------------------------------

            t_convert_start = time.perf_counter()

            audio_bytes = b"".join(
                audio_chunks
            )


            audio = np.frombuffer(
                audio_bytes,
                dtype=np.int16
            )


            audio = (
                audio.astype(
                    np.float32
                )
                / 32768.0
            )

            t_convert_end = time.perf_counter()


            # ------------------------------------------------
            # Process audio
            # ------------------------------------------------

            t_process_start = time.perf_counter()

            audio = process_audio(
                audio,
                sample_rate
            )

            t_process_end = time.perf_counter()


            print(
                "JARVIS TTS PERF: "
                f"synthesis={t_synth_end - t_synth_start:.3f}s | "
                f"convert={t_convert_end - t_convert_start:.3f}s | "
                f"process={t_process_end - t_process_start:.3f}s"
            )


            print(
                "JARVIS TTS: Piper inference = "
                + (
                    "CUDA"
                    if _using_cuda
                    else "CPU"
                )
            )


            print(
                f"JARVIS TTS: Playing on "
                f"output device {OUTPUT_DEVICE}..."
            )


            # ------------------------------------------------
            # Prepare exact playback reference for speaker-echo detection.
            # ------------------------------------------------

            playback_reference = _prepare_playback_reference(
                audio,
                sample_rate
            )

            with _playback_reference_lock:
                global _playback_reference
                global _playback_reference_started_at

                _playback_reference = playback_reference
                _playback_reference_started_at = 0.0

            # ------------------------------------------------
            # Start microphone monitor
            # ------------------------------------------------

            monitor_thread = threading.Thread(
                target=_monitor_microphone,
                daemon=True
            )


            monitor_thread.start()


            # ------------------------------------------------
            # Audio diagnostics
            # ------------------------------------------------

            print(
                f"JARVIS TTS: max amplitude before playback = "
                f"{np.max(np.abs(audio)):.4f}"
            )

            print(
                "JARVIS TTS PERF: "
                f"audio_duration={len(audio) / sample_rate:.3f}s"
            )

            print(
                f"JARVIS TTS: OUTPUT_GAIN = {OUTPUT_GAIN}"
            )

            # ------------------------------------------------
            # Start playback
            # ------------------------------------------------

            t_playback_start = time.perf_counter()

            with _playback_reference_lock:
                _playback_reference_started_at = time.monotonic()

            sd.play(
                audio,
                sample_rate,
                device=OUTPUT_DEVICE,
                blocking=False
            )


            # ------------------------------------------------
            # Monitor playback.
            # ------------------------------------------------

            while True:

                # --------------------------------------------
                # User interruption
                # --------------------------------------------

                if _interrupted_event.is_set():

                    print(
                        "JARVIS TTS: "
                        "Playback interrupted."
                    )

                    sd.stop()

                    break


                # --------------------------------------------
                # Check playback stream.
                # --------------------------------------------

                try:

                    stream = sd.get_stream()

                    if (
                        stream is None
                        or not stream.active
                    ):

                        break

                except Exception:

                    # Give PortAudio a moment and continue.

                    time.sleep(
                        0.02
                    )

                    continue


                time.sleep(
                    0.01
                )

            t_playback_end = time.perf_counter()

            print(
                "JARVIS TTS PERF: "
                f"playback={t_playback_end - t_playback_start:.3f}s"
            )


            # ------------------------------------------------
            # Tell monitor to stop.
            #
            # IMPORTANT:
            # This does NOT mean interruption occurred.
            # ------------------------------------------------

            _monitor_stop_event.set()


            try:

                monitor_thread.join(
                    timeout=0.50
                )

            except Exception:
                pass


            # ------------------------------------------------
            # Stop output.
            # ------------------------------------------------

            sd.stop()

            with _playback_reference_lock:
                _playback_reference = None
                _playback_reference_started_at = 0.0

            if _echo_canceller is not None:
                try:
                    _echo_canceller.reset()
                except Exception:
                    pass


            # ------------------------------------------------
            # Final status.
            # ------------------------------------------------

            interrupted = _interrupted_event.is_set()

            if interrupted:

                print(
                    "JARVIS TTS: "
                    "Barge-in successful."
                )

            else:

                print(
                    "JARVIS TTS: "
                    "Playback complete."
                )

            print(
                "JARVIS TTS PERF: "
                f"total={time.perf_counter() - t_total_start:.3f}s"
            )

            return interrupted


        except Exception as e:

            print(
                "JARVIS TTS error:",
                e
            )


            # Always stop monitor and audio if an
            # unexpected error occurs.

            _monitor_stop_event.set()


            try:

                sd.stop()

            except Exception:
                pass

            with _playback_reference_lock:
                _playback_reference = None
                _playback_reference_started_at = 0.0

            return False


# ============================================================
# TTS STATUS
# ============================================================

def tts_status():

    return {
        "loaded": _voice is not None,
        "cuda": _using_cuda,
        "provider": "CUDA" if _using_cuda else "CPU",
        "onnx_providers": list(_available_onnx_providers),
        "voice_model": str(VOICE_MODEL),
        "interrupted": _interrupted_event.is_set(),
    }
