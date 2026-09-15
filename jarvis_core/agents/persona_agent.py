"""
JARVIS Persona Agent - Applies personality, tone, and style to responses.
"""
from typing import Any

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context

logger = get_logger(__name__)


PERSONA_PROMPT_TEMPLATE = """
You are JARVIS's personality filter. Your sole task is to restyle
the given response to match the specified persona parameters.

=== Persona Profile ===
Persona:    {persona_name}
Formality:  {formality}/1.0 (0 = casual, 1 = formal)
Verbosity:  {verbosity}/1.0 (0 = terse, 1 = thorough)
Humor:      {humor}/1.0 (0 = deadpan, 1 = witty)
Jargon:     {jargon}/1.0 (0 = plain, 1 = technical)
Style:      {response_style}
User:       {user_name}

=== Instructions ===
Restyle the response below to match this persona. The restyled output
must convey exactly the same information — only the presentation
changes.

=== Style Mapping ===
conversational — natural language, contractions, relaxed but never slang
concise        — bullet points or short sentences, max 3 sentences, no padding
detailed       — thorough explanations, concrete examples, structured breakdown
expressive     — varied vocabulary, occasional metaphor, vivid phrasing
technical      — precise terminology, structured logic, minimal embellishment

=== Tone Guidance ===
• Adopt British spelling where applicable (colour, optimise, recognise)
• Inject subtle dry wit when humor exceeds 0.3 — never forced, never slapstick
• Use technical precision when jargon exceeds 0.7 — exact terms, no fluff
• Address {user_name} directly and naturally in conversation

=== Constraints ===
• Never invent, add, or fabricate information not present in the original
• Never insert explanations, disclaimers, or meta-commentary
• Return the restyled response as plain text only

Restyled response:"""


class PersonaAgent(Agent):
    name = "persona"
    description = "Personality and style adaptation"

    def __init__(self):
        self._client = None
        self._model = None

    async def initialize(self) -> None:
        from ollama import AsyncClient
        settings = get_settings()
        self._client = AsyncClient(host=settings.models.ollama_host)
        self._model = settings.models.chat_model
        logger.debug("PersonaAgent initialized")

    async def shutdown(self) -> None:
        pass

    async def process(self, input_data: Any, context: Context) -> Any:
        response = input_data.get("response", "")
        if not response:
            return response

        settings = get_settings()
        persona = settings.persona
        user_name = context.user_preferences.get("name", "User")

        prompt = PERSONA_PROMPT_TEMPLATE.format(
            persona_name=persona.name,
            formality=persona.formality,
            verbosity=persona.verbosity,
            humor=persona.humor,
            jargon=persona.jargon,
            response_style=persona.response_style,
            user_name=user_name,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Rewrite this response:\n\n{response}"},
        ]

        try:
            result = await self._client.chat(
                model=self._model,
                messages=messages,
                options={"temperature": 0.7},
            )

            styled = result.get("message", {}).get("content", "").strip()
            return styled if styled else response

        except Exception as e:
            logger.error(f"Persona agent error: {e}")
            return response
