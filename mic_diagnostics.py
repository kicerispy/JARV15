


def score_heed_audio(
    audio: np.ndarray,
) -> tuple[float, float, int, float]:
    """
    Run the actual Heed model over 1-second windows of a captured recording.

    Returns:
        max score, median score, number of windows at/above the trained
        threshold, and best-window offset in seconds.
    """
    import torch
    from heed.audio import StreamingHighpass, log_mel
    from wakeword import (
        INPUT_NAME,
        OUTPUT_NAME,
        WAKE_THRESHOLD,
        session,
    )

    values = np.asarray(
        audio,
        dtype=np.float32,
    ).reshape(-1)

    if len(values) < WAKE_WINDOW_SAMPLES:
        return 0.0, 0.0, 0, -1

    # Match wakeword.py's streaming high-pass/notch preprocessing.
    preprocessor = StreamingHighpass(
        cutoff_hz=100.0,
        sample_rate=SAMPLE_RATE,
        order=8,
        apply_mains_notch=True,
    )

    filtered = np.asarray(
        preprocessor(values),
        dtype=np.float32,
    )

    scores: list[float] = []
    best_score = -1.0
    best_offset = -1

    max_start = (
        len(filtered) - WAKE_WINDOW_SAMPLES
    )

    for start in range(
        0,
        max_start + 1,
        WAKE_WINDOW_STEP_SAMPLES,
    ):
        window = filtered[
            start : start + WAKE_WINDOW_SAMPLES
        ].copy()

        peak = float(
            np.max(
                np.abs(window)
            )
        )

        if peak <= 1e-6:
            continue

        # Match the level floor used by live activation before applying
        # peak normalization. Otherwise very quiet room noise can be
        # amplified into a misleadingly strong model input.
        rms = float(
            np.sqrt(
                np.mean(
                    np.square(window)
                )
            )
        )

        if rms <= 1e-12:
            continue

        window_dbfs = 20.0 * math.log10(rms)

        if window_dbfs < -55.0:
            continue

        # Match the -3 dBFS peak normalization specified by wake.json.
        window = np.clip(
            window
            * (WAKE_PEAK_TARGET_AMPLITUDE / peak),
            -WAKE_PEAK_TARGET_AMPLITUDE,
            WAKE_PEAK_TARGET_AMPLITUDE,
        ).astype(
            np.float32,
            copy=False,
        )

        waveform = torch.from_numpy(window)

        mel = log_mel(
            waveform,
            apply_cmn=True,
        )

        mel_np = (
            mel.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )

        outputs = session.run(
            [OUTPUT_NAME],
            {
                INPUT_NAME: mel_np,
            },
        )

        logit = float(
            np.asarray(
                outputs[0]
            ).reshape(-1)[0]
        )

        score = 1.0 / (
            1.0 + np.exp(-logit)
        )

        scores.append(float(score))

        if score > best_score:
            best_score = float(score)
            best_offset = start

    if not scores:
        return 0.0, 0.0, 0, -1

    return (
        max(scores),
        float(np.median(scores)),
        sum(
            score >= WAKE_THRESHOLD
            for score in scores
        ),
        float(
            best_offset / SAMPLE_RATE
        ),
    )


def print_heed_scores(
    label: str,
    audio: np.ndarray,
) -> tuple[float, float, int, float]:
    from wakeword import WAKE_THRESHOLD

    print()
    print(f"===== {label} HEED MODEL =====")
    print("Running the actual wake model over the recording (live -55 dBFS energy floor applied)...")
