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


# ============================================================
# DEVICE / AUDIO SETTINGS
# ============================================================

OUTPUT_DEVICE = 5
MIC_DEVICE = 1

SAMPLE_RATE = 16000


VOICE_MODEL = os.path.expanduser(
    r"~/.heed/voices/en_GB-alan-medium.onnx"
)


# ============================================================
# PIPER VOICE SETTINGS
# ============================================================

# Higher = slower.

LENGTH_SCALE = 1.05

NOISE_SCALE = 0.45

NOISE_W_SCALE = 0.60


# ============================================================
# JARVIS AUDIO CHARACTER
# ============================================================

# Slightly lower pitch.

PITCH_RATIO = 0.94


# Warm low frequencies.

LOW_SHELF_GAIN_DB = 3.0


# Slightly reduce upper-mid harshness.

PRESENCE_GAIN_DB = -1.5


# Slightly soften highs.

HIGH_GAIN_DB = -1.5


# Gentle compression.

COMP_THRESHOLD = 0.55

COMP_RATIO = 2.2


# Final volume.

OUTPUT_GAIN = 0.30


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
# MICROPHONE BARGE-IN MONITOR
# ============================================================

def _monitor_microphone():

    global _interrupted_audio


    ring_buffer = collections.deque(
        maxlen=PREBUFFER_CHUNKS
    )


    consecutive_loud = 0


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


                volume = _get_volume(
                    audio
                )


                # -----------------------------------------
                # Sustained speech detection.
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

                if (
                    consecutive_loud
                    >= INTERRUPT_CHUNKS
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
