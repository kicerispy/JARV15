import time
import numpy as np
import sounddevice as sd
import config

print("Listening for 8 seconds...")
print("Speak normally after about 1 second.")

stream = sd.InputStream(
    samplerate=config.SAMPLE_RATE,
    blocksize=config.CHUNK_SIZE,
    channels=1,
    dtype="int16",
    device=config.MIC_DEVICE,
)

stream.start()

start = time.perf_counter()
last = 0
peak = 0

try:
    while time.perf_counter() - start < 8:
        audio, overflowed = stream.read(config.CHUNK_SIZE)

        samples = np.asarray(
            audio[:, 0],
            dtype=np.int16
        )

        volume = float(
            np.sqrt(
                np.mean(
                    samples.astype(np.float32) ** 2
                )
            )
        )

        peak = max(peak, volume)

        now = time.perf_counter() - start

        if now - last >= 0.25:
            print(
                f"{now:5.2f}s  "
                f"volume={volume:7.1f}  "
                f"peak={peak:7.1f}"
            )
            last = now

finally:
    stream.stop()
    stream.close()

print("DONE")
