import numpy as np

from mic_diagnostics import measure_signal


def test_measure_signal_reports_known_rms_and_peak():
    audio = np.array(
        [0, 100, -100, 200, -200, 0],
        dtype=np.int16,
    )

    stats = measure_signal(audio, 16000)

    expected_rms = float(
        np.sqrt(
            np.mean(
                audio.astype(np.float32) ** 2
            )
        )
    )

    assert stats.samples == 6
    assert stats.duration == 6 / 16000
    assert stats.rms == expected_rms
    assert stats.peak == 200
    assert stats.clip_percent == 0.0


def test_measure_signal_detects_clipping():
    audio = np.array(
        [0, 1000, 32767, -32768],
        dtype=np.int16,
    )

    stats = measure_signal(audio, 16000)

    assert stats.peak == 32768
    assert stats.clip_percent == 50.0
