"""
JARVIS Memory Agent - Long-term memory storage and retrieval.
"""
import json
from datetime import datetime
from typing import Any, Dict, List

from jarvis_core.config.settings import get_settings
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Agent, Context

logger = get_logger(__name__)


MEMORY_ANALYSIS_PROMPT = """
You decide if a user message contains information worth remembering long-term.

Remember:
- User preferences (likes, dislikes, settings)
- Personal facts (name, location, job, hobbies)
- Project context (goals, architecture decisions, key files)
- Important instructions or constraints
- Corrections or feedback on your behavior

Do NOT remember:
- Temporary questions or one-time requests
- Random conversation filler
- Transient state (current file, temporary variables)
- Information already in memory

If worth remembering, reply with JSON:
{{
  "save": true,
  "category": "preference|fact|project|instruction|correction",
  "key": "brief unique key",
  "value": "the information to remember",
  "confidence": 0.0-1.0
}}

If not, reply:
{{
  "save": false
}}
"""


class MemoryAgent(Agent):
    name = "memory"
    description = "Long-term memory management"

    def __init__(self):
        self._client = None
        self._model = None
        self._memory_store = None
        self._initialized = False

    async def initialize(self) -> None:
        from ollama import AsyncClient
        settings = get_settings()
        self._client = AsyncClient(host=settings.models.ollama_host)
        self._model = settings.models.chat_model

        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            persist_dir = str(settings.memory.vector_db_path)
            self._chroma_client = chromadb.PersistentClient(
                path=persist_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._chroma_client.get_or_create_collection("jarvis_memories")
            logger.debug("ChromaDB initialized for memory")
        except Exception as e:
            logger.warning(f"ChromaDB not available: {e}")
            self._chroma_client = None
            self._collection = None

        self._initialized = True
        logger.debug("MemoryAgent initialized")

    async def shutdown(self) -> None:
        pass

    async def process(self, input_data: Any, context: Context) -> Any:
        query = input_data.get("query", "")
        if not query:
            return ""

        if input_data.get("action") == "store":
            return await self._store_memory(input_data, context)
        elif input_data.get("action") == "retrieve":
            return await self._retrieve_memories(query, context)
        else:
            return await self._analyze_and_store(query, context)

    async def _analyze_and_store(self, text: str, context: Context) -> bool:
        if not self._initialized:
            await self.initialize()

        try:
            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": MEMORY_ANALYSIS_PROMPT},
                    {"role": "user", "content": text},
                ],
                format="json",
                options={"temperature": 0.1},
            )

            content = response.get("message", {}).get("content", "")
            result = json.loads(content)

            if result.get("save", False):
                await self._store_memory({
                    "category": result.get("category", "fact"),
                    "key": result.get("key", ""),
                    "value": result.get("value", ""),
                    "confidence": result.get("confidence", 0.5),
                }, context)
                return True

        except Exception as e:
            logger.warning(f"Memory analysis failed: {e}")

        return False

    async def _store_memory(self, data: Dict[str, Any], context: Context) -> str:
        if not self._collection:
            return ""

        import uuid
        memory_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        document = f"[{data.get('category', 'fact')}] {data.get('key', '')}: {data.get('value', '')}"
        metadata = {
            "category": data.get("category", "fact"),
            "key": data.get("key", ""),
            "confidence": data.get("confidence", 0.5),
            "timestamp": timestamp,
            "user_id": context.user_id,
            "conversation_id": context.conversation_id,
        }

        try:
            self._collection.add(
                documents=[document],
                metadatas=[metadata],
                ids=[memory_id],
            )
            context.long_term_memory_ids.append(memory_id)
            logger.debug(f"Stored memory: {data.get('key')}")
            return memory_id
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return ""

    async def _retrieve_memories(self, query: str, context: Context, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._collection:
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=limit,
                where={"user_id": context.user_id},
            )

            memories = []
            for i, doc in enumerate(results.get("documents", [[]])[0]):
                metadata = results.get("metadatas", [[]])[0][i]
                memories.append({
                    "content": doc,
                    "metadata": metadata,
                    "id": results.get("ids", [[]])[0][i],
                })

            return memories

        except Exception as e:
            logger.error(f"Failed to retrieve memories: {e}")
            return []
