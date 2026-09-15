import threading
import time
import numpy as np
import sounddevice as sd

import voice


MIC_DEVICE = 1
OUTPUT_DEVICE = 5
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024

TEST_TEXT = (
    "This is a microphone bleed test. "
    "JARVIS is speaking normally so we can measure "
    "how much of my voice reaches the microphone."
)


def measure_mic():

    values = []

    start_time = time.time()

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=CHUNK_SIZE,
        channels=1,
        dtype="int16",
        device=MIC_DEVICE
    ) as stream:

        while time.time() - start_time < 8:

            audio, overflowed = stream.read(
                CHUNK_SIZE
            )

            if overflowed:
                continue

            audio = audio[:, 0].astype(
                np.float32
            )

            rms = np.sqrt(
                np.mean(
                    audio ** 2
                )
            )

            values.append(rms)

    values = np.array(values)

    print()
    print("================================")
    print("JARVIS PLAYBACK MIC MEASUREMENT")
    print("================================")

    print(
        f"Average RMS : {values.mean():.1f}"
    )

    print(
        f"Median RMS  : {np.median(values):.1f}"
    )

    print(
        f"Maximum RMS : {values.max():.1f}"
    )

    print(
        f"95th %ile   : {np.percentile(values, 95):.1f}"
    )

    print(
        f"99th %ile   : {np.percentile(values, 99):.1f}"
    )


print()
print("Starting microphone monitor...")
print("Do not speak during the test.")
print()
print("JARVIS will speak in 2 seconds.")

time.sleep(2)

thread = threading.Thread(
    target=measure_mic,
    daemon=True
)

thread.start()


# IMPORTANT:
# We deliberately do NOT use voice.speak()
# because that contains the barge-in detector.
#
# Instead, synthesize and play Piper directly.

config = voice.SynthesisConfig(
    length_scale=voice.LENGTH_SCALE,
    noise_scale=voice.NOISE_SCALE,
    noise_w_scale=voice.NOISE_W_SCALE,
)

audio_chunks = []
sample_rate = None

for chunk in voice._voice.synthesize(
    TEST_TEXT,
    config
):

    if sample_rate is None:
        sample_rate = chunk.sample_rate

    audio_chunks.append(
        chunk.audio_int16_bytes
    )

audio_bytes = b"".join(
    audio_chunks
)

audio = np.frombuffer(
    audio_bytes,
    dtype=np.int16
).astype(
    np.float32
) / 32768.0


audio = voice.process_audio(
    audio,
    sample_rate
)


print()
print("JARVIS: Playing test audio...")

sd.play(
    audio,
    sample_rate,
    device=OUTPUT_DEVICE,
    blocking=True
)

sd.stop()

thread.join()

print()
print("Test complete.")