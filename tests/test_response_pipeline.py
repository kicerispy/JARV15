import response_pipeline


def test_clean_for_speech_removes_parentheses_and_urls():
    cleaned = response_pipeline.clean_for_speech(
        "Mars (the fourth planet from the Sun) is red. See https://example.com."
    )
    assert "(" not in cleaned
    assert ")" not in cleaned
    assert "https://" not in cleaned
    assert "fourth planet from the Sun" in cleaned


def test_split_for_speech_preserves_sentences():
    chunks = response_pipeline.split_for_speech(
        "First sentence. Second sentence. Third sentence.",
        max_chars=20,
    )
    assert chunks == ["First sentence.", "Second sentence.", "Third sentence."]


def test_speak_response_speaks_all_chunks():
    spoken = []
    interrupted = response_pipeline.speak_response(
        "One sentence. Two sentence. Three sentence.",
        lambda text: spoken.append(text) or False,
        max_chars=20,
    )
    assert interrupted is False
    assert spoken == ["One sentence.", "Two sentence.", "Three sentence."]


def test_speak_response_stops_on_interrupt():
    spoken = []

    def fake_speak(text):
        spoken.append(text)
        return len(spoken) == 2

    interrupted = response_pipeline.speak_response(
        "One. Two. Three.",
        fake_speak,
        max_chars=8,
    )
    assert interrupted is True
    assert spoken == ["One.", "Two."]
