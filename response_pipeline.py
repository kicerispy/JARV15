"""JARVIS response-to-speech pipeline.

Separates model output from TTS input and guarantees that multi-sentence
responses are spoken in order.
"""

from __future__ import annotations

import re
from typing import Callable, List

MAX_SPEECH_CHARS = 320


def clean_for_speech(text: str) -> str:
    """Convert model output into natural text for TTS."""
    if text is None:
        return ""

    text = str(text).strip()
    if not text:
        return ""

    text = re.sub(r"^\s*(?:```)+", "", text)
    text = text.replace(chr(96), "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.*?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!_)_(?!\s)(.*?)(?<!\s)_", r"\1", text, flags=re.DOTALL)

    # Do not spell the shorthand plural marker "(s)" aloud as
    # "comma s"; normalize it before the general parenthesis handling.
    text = re.sub(r"\((?:s|es)\)", "", text, flags=re.IGNORECASE)

    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\(([^()]*)\)", r", \1", text)

    text = re.sub(r"\[([^\[\]]*)\]", r", \1", text)
    text = re.sub(r"https?://\S+", "the linked page", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(?:JARVIS|ASSISTANT)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([.!?]){2,}", r"\1", text)

    return text.strip(" \t\r\n")


def _split_long_piece(piece: str, max_chars: int) -> List[str]:
    words = piece.split()
    if not words:
        return []

    chunks = []
    current = []
    current_len = 0

    for word in words:
        projected = current_len + len(word) + (1 if current else 0)
        if projected > max_chars and current:
            chunks.append(" ".join(current).strip())
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len = projected

    if current:
        chunks.append(" ".join(current).strip())

    return chunks


def split_for_speech(text: str, max_chars: int = MAX_SPEECH_CHARS) -> List[str]:
    """Split cleaned speech at sentence and word boundaries."""
    cleaned = clean_for_speech(text)
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    chunks = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_piece(sentence, max_chars))
            continue

        projected = len(current) + len(sentence) + (1 if current else 0)
        if current and projected > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current:
        chunks.append(current)

    return chunks


def speak_response(
    text: str,
    speak_callback: Callable[[str], bool],
    max_chars: int = MAX_SPEECH_CHARS,
) -> bool:
    """Speak every chunk in order; return True only on user interruption."""
    chunks = split_for_speech(text, max_chars=max_chars)
    for chunk in chunks:
        if bool(speak_callback(chunk)):
            return True
    return False
