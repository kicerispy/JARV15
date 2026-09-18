import time
import numpy as np
import sounddevice as sd
import config

print("Starting in 2 seconds...")
time.sleep(2)

print("SPEAK NOW — say: TEST TEST TEST")

stream = sd.InputStream(
    samplerate=config.SAMPLE_RATE,
    blocksize=config.CHUNK_SIZE,
    channels=1,
    dtype="int16",
    device=config.MIC_DEVICE,
)

stream.start()

start = time.perf_counter()
detected = False

try:
    while time.perf_counter() - start < 6:
        audio, overflowed = stream.read(config.CHUNK_SIZE)

        samples = np.asarray(audio[:, 0], dtype=np.int16)

        volume = float(
            np.sqrt(
                np.mean(samples.astype(np.float32) ** 2)
            )
        )

        elapsed = time.perf_counter() - start

        if volume > config.SILENCE_THRESHOLD and not detected:
            detected = True
            print()
            print("================================")
            print(f"SPEECH DETECTED AFTER {elapsed:.3f}s")
            print(f"Volume: {volume:.1f}")
            print("================================")
            break

finally:
    stream.stop()
    stream.close()

if not detected:
    print("NO SPEECH DETECTED")
