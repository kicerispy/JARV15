"""Deterministic regression tests for JARVIS wake temporal fusion."""

from activation_controller import evaluate_wake_scores


def assert_trigger(
    scores: list[float],
    expected: bool,
    label: str,
) -> None:
    decision = evaluate_wake_scores(
        scores,
        [1.0] * len(scores),
    )

    if decision.triggered != expected:
        raise AssertionError(
            f"{label}: expected triggered={expected}, "
            f"got {decision.triggered} "
            f"(reason={decision.reason}, scores={scores})"
        )


def main() -> int:
    # Known false-positive shape from the holdout:
    # strong scores are separated by weaker frames, so it must stay quiet.
    assert_trigger(
        [0.701, 0.383, 0.116, 0.811, 0.127],
        False,
        "isolated high false-positive shape",
    )

    # The same score region becomes valid when the strong candidates are
    # consecutive, matching Heed's own trigger behavior.
    assert_trigger(
        [0.701, 0.650],
        True,
        "consecutive moderate wake",
    )

    # A strong isolated score remains valid at the new single-frame threshold.
    assert_trigger(
        [0.95],
        True,
        "very strong single wake",
    )

    # A medium isolated score must no longer activate.
    assert_trigger(
        [0.811],
        False,
        "isolated medium wake",
    )

    # A natural sequence from the holdout remains valid.
    assert_trigger(
        [0.867, 0.628, 0.654],
        True,
        "natural positive sequence",
    )

    print("All wake fusion regression tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
