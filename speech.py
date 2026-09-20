import time
from collections import deque
from typing import Any, Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from scipy.io.wavfile import write

from adaptive_speech_gate import AdaptiveSpeechGate

from config import (
    BARGE_IN_MINIMUM_CAPTURE,
    BARGE_IN_SILENCE_DURATION,
    CHUNK_SIZE,
    CONTINUOUS_START_TIMEOUT,
    MAX_RECORDING_SECONDS,
    MIC_DEVICE,
    PREBUFFER_SECONDS,
    SAMPLE_RATE,
    SILENCE_DURATION,
    SILENCE_THRESHOLD,
    START_TIMEOUT,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)


# ============================================================
# AUDIO BUFFER SETTINGS
# ============================================================

PREBUFFER_CHUNKS = max(
    1,
    int(
        PREBUFFER_SECONDS
        * SAMPLE_RATE
        / CHUNK_SIZE
    )
)


# ============================================================
# WHISPER
# ============================================================

device = WHISPER_DEVICE

print(
    f"Whisper running on: {WHISPER_DEVICE} "
    f"({WHISPER_COMPUTE_TYPE})"
)

model = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE_TYPE,
)


# ============================================================
# GET MICROPHONE VOLUME
# ============================================================

def get_volume(audio):

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
# LISTEN
#
# mode:
#   "wake"       = normal wake-word interaction
#   "continuous" = follow-up conversation
#
# initial_audio:
#   Optional audio captured by the TTS barge-in monitor.
# ============================================================

def listen(
    initial_audio=None,
    mode="wake",
    interrupt_event: Optional[Any] = None,
):

    print(
        "JARVIS: Listening..."
    )

    # --------------------------------------------------------
    # Determine whether this is a barge-in capture.
    # --------------------------------------------------------

    is_barge_in = (
        initial_audio is not None
    )

    # --------------------------------------------------------
    # Select startup timeout.
    # --------------------------------------------------------

    if mode == "continuous":

        start_timeout = (
            CONTINUOUS_START_TIMEOUT
        )

    else:

        start_timeout = (
            START_TIMEOUT
        )

    # --------------------------------------------------------
    # Recording state.
    # --------------------------------------------------------

    recorded_chunks = []

    speech_started = False

    silence_start = None

    start_time = time.time()

    recording_start_time = None

    # --------------------------------------------------------
    # Keep recent microphone audio before speech detection.
    #
    # This prevents the beginning of a command from being
    # lost while the volume detector catches up.
    # --------------------------------------------------------

    prebuffer = deque(
        maxlen=PREBUFFER_CHUNKS
    )

    speech_gate = AdaptiveSpeechGate(
        legacy_threshold=float(SILENCE_THRESHOLD)
    )

    # ========================================================
    # INITIAL BARGE-IN AUDIO
    # ========================================================

    if initial_audio is not None:

        initial_audio = np.asarray(
            initial_audio,
            dtype=np.int16
        )

        if len(initial_audio) > 0:

            recorded_chunks.append(
                initial_audio.copy()
            )

            speech_started = True

            recording_start_time = (
                time.time()
            )

            print(
                "JARVIS: "
                "Initial barge-in audio received."
            )

            print(
                f"JARVIS: "
                f"Barge-in samples = "
                f"{len(initial_audio)}"
            )

            print(
                f"JARVIS: "
                f"Barge-in volume = "
                f"{get_volume(initial_audio):.1f}"
            )

    # ========================================================
    # OPEN MICROPHONE
    # ========================================================

    try:

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            channels=1,
            dtype="int16",
            device=MIC_DEVICE
        ) as stream:

            while True:

                # A background task finishing should release the main loop
                # while it is waiting for a new follow-up command. Once the
                # user has started speaking, do not interrupt the capture.
                if (
                    interrupt_event is not None
                    and not speech_started
                    and interrupt_event.is_set()
                ):
                    print(
                        "JARVIS: Background task completed while waiting for follow-up."
                    )
                    return None

                # ------------------------------------------------
                # Read microphone chunk.
                # ------------------------------------------------

                audio, overflowed = (
                    stream.read(
                        CHUNK_SIZE
                    )
                )

                if overflowed:

                    print(
                        "JARVIS: "
                        "Microphone overflow."
                    )

                    continue

                # ------------------------------------------------
                # Convert to mono.
                # ------------------------------------------------

                audio = np.asarray(
                    audio[:, 0],
                    dtype=np.int16
                )

                # ------------------------------------------------
                # Calculate microphone volume.
                # ------------------------------------------------

                volume = get_volume(
                    audio
                )

                if not speech_started:
                    start_threshold, end_threshold = (
                        speech_gate.update(volume)
                    )
                else:
                    start_threshold = speech_gate.start_threshold
                    end_threshold = speech_gate.end_threshold

                current_time = time.time()

                # ------------------------------------------------
                # Always keep recent audio in the prebuffer.
                # ------------------------------------------------

                prebuffer.append(
                    audio.copy()
                )

                # ==================================================
                # WAITING FOR USER TO BEGIN SPEAKING
                # ==================================================

                if not speech_started:

                    if (
                        volume
                        > start_threshold
                    ):

                        speech_started = True

                        recording_start_time = (
                            current_time
                        )

                        # ------------------------------------------
                        # Include audio immediately before speech.
                        # ------------------------------------------

                        recorded_chunks.extend(
                            list(prebuffer)
                        )

                        silence_start = None

                        print(
                            "JARVIS: "
                            "Speech detected."
                        )

                        print(
                            f"JARVIS: "
                            f"Start volume = "
                            f"{volume:.1f}"
                        )

                        print(
                            f"JARVIS: "
                            f"Adaptive threshold = "
                            f"{start_threshold:.1f} "
                            f"(noise floor={speech_gate.noise_floor:.1f})"
                        )

                    elif (
                        current_time
                        - start_time
                        >= start_timeout
                    ):

                        print(
                            "JARVIS: "
                            "I didn't hear anything."
                        )

                        return None

                    continue

                # ==================================================
                # USER IS SPEAKING
                # ==================================================

                recorded_chunks.append(
                    audio.copy()
                )

                # ==================================================
                # BARGE-IN CAPTURE PROTECTION
                # ==================================================

                if is_barge_in:

                    elapsed_capture = (
                        current_time
                        - recording_start_time
                    )

                    if (
                        elapsed_capture
                        < BARGE_IN_MINIMUM_CAPTURE
                    ):

                        silence_start = None

                        continue

                # ==================================================
                # DETECT END OF SPEECH
                # ==================================================

                silence_limit = (
                    BARGE_IN_SILENCE_DURATION
                    if is_barge_in
                    else SILENCE_DURATION
                )

                if (
                    volume
                    < end_threshold
                ):

                    if silence_start is None:

                        silence_start = (
                            current_time
                        )

                    elif (
                        current_time
                        - silence_start
                        >= silence_limit
                    ):

                        print(
                            "JARVIS: "
                            "End of speech detected."
                        )

                        break

                else:

                    silence_start = None

                # ==================================================
                # MAXIMUM RECORDING TIME
                # ==================================================

                if (
                    current_time
                    - start_time
                    >= MAX_RECORDING_SECONDS
                ):

                    print(
                        "JARVIS: "
                        "Maximum recording time reached."
                    )

                    break

    except Exception as e:

        print(
            "JARVIS microphone error:",
            e
        )

        return None

    # ========================================================
    # MAKE SURE WE HAVE AUDIO
    # ========================================================

    if not recorded_chunks:

        print(
            "JARVIS: "
            "No microphone chunks captured."
        )

        return None

    # --------------------------------------------------------
    # Combine all captured chunks.
    # --------------------------------------------------------

    audio_data = np.concatenate(
        recorded_chunks
    ).astype(
        np.int16
    )

    # ========================================================
    # AUDIO DIAGNOSTICS
    # ========================================================

    duration = (
        len(audio_data)
        / SAMPLE_RATE
    )

    rms = get_volume(
        audio_data
    )

    peak = int(
        np.max(
            np.abs(
                audio_data.astype(
                    np.int32
                )
            )
        )
    )

    print()
    print(
        "========== JARVIS AUDIO =========="
    )

    print(
        f"Samples:   {len(audio_data)}"
    )

    print(
        f"Duration:  {duration:.2f}s"
    )

    print(
        f"RMS:       {rms:.1f}"
    )

    print(
        f"Peak:      {peak}"
    )

    print(
        f"Start threshold: {speech_gate.start_threshold:.1f}"
    )

    print(
        f"End threshold:   {speech_gate.end_threshold:.1f}"
    )

    print(
        f"Noise floor:     {speech_gate.noise_floor:.1f}"
    )

    print(
        "=================================="
    )

    # ========================================================
    # REMOVE VERY SHORT / EMPTY CAPTURES
    # ========================================================

    minimum_samples = int(
        0.20
        * SAMPLE_RATE
    )

    if len(audio_data) < minimum_samples:

        print(
            "JARVIS: "
            "Audio capture too short."
        )

        return None

    if rms < 1.0:

        print(
            "JARVIS: "
            "Captured audio is essentially silent."
        )

        return None

    # ========================================================
    # SAVE RECORDING
    # ========================================================

    filename = "input.wav"

    try:

        write(
            filename,
            SAMPLE_RATE,
            audio_data
        )

        print(
            f"JARVIS: "
            f"Saved recording to {filename}"
        )

    except Exception as e:

        print(
            "JARVIS audio save error:",
            e
        )

        return None

    # ========================================================
    # WHISPER TRANSCRIPTION
    # ========================================================

    try:

        print(
            "JARVIS: "
            "Sending audio to Whisper..."
        )

        segments, _info = model.transcribe(
            filename,
            language="en",
            temperature=0,
        )

        segments = list(segments)

    except Exception as e:

        print(
            "Whisper error:",
            e
        )

        return None

    # ========================================================
    # CLEAN TRANSCRIPTION
    # ========================================================

    text = " ".join(
        segment.text
        for segment in segments
    ).strip()

    if not text:

        print(
            "JARVIS: "
            "Whisper returned empty text."
        )

        print(
            f"JARVIS: Whisper segments = "
            f"{len(segments)}"
        )

        return None

    # --------------------------------------------------------
    # Collapse repeated whitespace.
    # --------------------------------------------------------

    text = " ".join(
        text.split()
    )

    print(
        "You:",
        text
    )

    return text