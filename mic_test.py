import sounddevice as sd
import numpy as np
import time

MIC_DEVICE = 1
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024

print("Starting microphone level test...")
print("Stay silent for 5 seconds.")

values = []

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    blocksize=CHUNK_SIZE,
    channels=1,
    dtype="int16",
    device=MIC_DEVICE
) as stream:

    start = time.time()

    while time.time() - start < 5:

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

        values.append(
            rms
        )

        time.sleep(0.01)


values = np.array(values)

print()
print("----- SILENCE RESULTS -----")
print(f"Average RMS : {values.mean():.1f}")
print(f"Median RMS  : {np.median(values):.1f}")
print(f"Maximum RMS : {values.max():.1f}")

print()
print("Now speak normally for 5 seconds.")

values = []

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    blocksize=CHUNK_SIZE,
    channels=1,
    dtype="int16",
    device=MIC_DEVICE
) as stream:

    start = time.time()

    while time.time() - start < 5:

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

        values.append(
            rms
        )

        time.sleep(0.01)


values = np.array(values)

print()
print("----- YOUR VOICE RESULTS -----")
print(f"Average RMS : {values.mean():.1f}")
print(f"Median RMS  : {np.median(values):.1f}")
print(f"Maximum RMS : {values.max():.1f}")

print()
print("Test complete.")