"""
Adaptive microphone speech gate for JARVIS.

The gate learns the local microphone noise floor while waiting for speech,
then derives separate start/end thresholds with hysteresis. This avoids making
quiet users move closer to the microphone just to cross one fixed RMS value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass
class AdaptiveSpeechGate:
    """
    Derive speech start/end thresholds from the local noise floor.

    The configured legacy threshold remains the upper bound so a noisy room
    cannot make the detector arbitrarily permissive.
    """

    legacy_threshold: float = 200.0
    min_start_threshold: float = 90.0
    noise_multiplier: float = 2.25
    end_ratio: float = 0.65
    min_end_threshold: float = 60.0
    calibration_chunks: int = 8
    initial_noise_floor: float = 40.0
    _samples: list[float] = field(default_factory=list)
    _noise_floor: float = 40.0

    def __post_init__(self) -> None:
        self._noise_floor = float(self.initial_noise_floor)

    @staticmethod
    def _clamp(
        value: float,
        lower: float,
        upper: float,
    ) -> float:
        return max(lower, min(value, upper))

    def _recalculate_noise_floor(self) -> None:
        if not self._samples:
            return

        ordered = sorted(self._samples)

        # Favor the quieter part of the startup window. If the user begins
        # speaking immediately, louder speech does not dominate the estimate.
        quiet_count = max(
            1,
            int(len(ordered) * 0.60),
        )

        quiet_values = ordered[:quiet_count]
        self._noise_floor = float(
            median(quiet_values)
        )

    def update(
        self,
        volume: float,
    ) -> tuple[float, float]:
        """
        Observe one RMS measurement and return (start_threshold, end_threshold).
        """

        volume = max(0.0, float(volume))

        start_threshold = self.start_threshold

        if (
            len(self._samples) < self.calibration_chunks
            and volume <= self.legacy_threshold
        ):
            self._samples.append(volume)
            self._recalculate_noise_floor()

            start_threshold = self.start_threshold

        elif (
            volume < self._noise_floor
            and volume < self.legacy_threshold
        ):
            # Only track measurements below the current noise floor. A quiet
            # speech frame can be louder than the floor without turning into a
            # new baseline and raising the start threshold mid-session.
            self._noise_floor = (
                0.90 * self._noise_floor
                + 0.10 * volume
            )

            start_threshold = self.start_threshold

        return (
            start_threshold,
            self.end_threshold,
        )

    @property
    def noise_floor(self) -> float:
        return float(self._noise_floor)

    @property
    def start_threshold(self) -> float:
        return self._clamp(
            self._noise_floor * self.noise_multiplier,
            self.min_start_threshold,
            self.legacy_threshold,
        )

    @property
    def end_threshold(self) -> float:
        return max(
            self.min_end_threshold,
            self.start_threshold * self.end_ratio,
        )

    def reset(self) -> None:
        self._samples.clear()
        self._noise_floor = float(self.initial_noise_floor)
