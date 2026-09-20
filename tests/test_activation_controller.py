from activation_controller import evaluate_wake_scores


def test_natural_near_threshold_wake():
    decision = evaluate_wake_scores(
        [0.48, 0.711, 0.315, 0.538, 0.713],
        [0.72, 0.81, 0.78, 0.84, 0.81],
    )

    assert decision.triggered is True
    assert decision.reason == "multi-frame wake confirmation"


def test_single_strong_wake():
    decision = evaluate_wake_scores(
        [0.31, 0.78],
        [0.80, 0.82],
    )

    assert decision.triggered is True
    assert decision.reason == "strong single-frame wake"


def test_silence_does_not_activate():
    decision = evaluate_wake_scores(
        [0.52, 0.58, 0.61],
        [0.08, 0.12, 0.10],
    )

    assert decision.triggered is False
    assert decision.reason == "insufficient speech support"


def test_active_task_requires_high_confidence():
    decision = evaluate_wake_scores(
        [0.71, 0.73, 0.80],
        [0.80, 0.82, 0.79],
        active_task=True,
    )

    assert decision.triggered is False
    assert decision.reason == "active-task confidence insufficient"


def test_active_task_accepts_high_confidence_wake():
    decision = evaluate_wake_scores(
        [0.61, 0.94],
        [0.78, 0.84],
        active_task=True,
    )

    assert decision.triggered is True
    assert decision.reason == "strong active-task wake"
