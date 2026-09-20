from adaptive_speech_gate import AdaptiveSpeechGate


def test_quiet_room_gets_lower_start_threshold():
    gate = AdaptiveSpeechGate(
        legacy_threshold=200,
        min_start_threshold=90,
        initial_noise_floor=40,
    )

    for volume in [35, 37, 39, 41, 45, 47, 49, 51]:
        gate.update(volume)

    assert gate.noise_floor == 38.0
    assert gate.start_threshold == 90.0
    assert gate.end_threshold == 60.0


def test_louder_room_stays_bounded():
    gate = AdaptiveSpeechGate(
        legacy_threshold=200,
        initial_noise_floor=70,
    )

    for volume in [70, 75, 80, 72, 78, 74, 76, 73]:
        gate.update(volume)

    assert gate.start_threshold <= 200
    assert gate.end_threshold < gate.start_threshold


def test_quieter_speech_can_cross_dynamic_start_threshold():
    gate = AdaptiveSpeechGate(
        legacy_threshold=200,
        initial_noise_floor=40,
    )

    for volume in [35, 38, 42, 39, 41, 37, 40, 36]:
        gate.update(volume)

    start, end = gate.update(115)

    assert start == 90.0
    assert end == 60.0
    assert 115 > start
    assert 115 > end


def test_low_speech_does_not_raise_threshold_during_calibration():
    gate = AdaptiveSpeechGate(
        legacy_threshold=200,
        initial_noise_floor=40,
    )

    for volume in [35, 38, 42, 39, 41, 37, 40, 36]:
        gate.update(volume)

    before = gate.start_threshold
    gate.update(80)
    after = gate.start_threshold

    assert after <= before
