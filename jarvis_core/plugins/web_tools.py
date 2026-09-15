"""
JARVIS Web Tools Plugin - Web search and browsing.
"""
import asyncio
import json
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from jarvis_core.config.settings import get_settings
from jarvis_core.plugins.base import BasePlugin
from jarvis_core.utils.logging import get_logger
from jarvis_core.utils.types import Context, Tool, ToolResult, ToolResultStatus

logger = get_logger(__name__)


class WebToolsPlugin(BasePlugin):
    @property
    def manifest(self):
        from jarvis_core.utils.types import PluginManifest
        return PluginManifest(
            name="web_tools",
            version="1.0.0",
            description="Web search and content retrieval",
            author="JARVIS",
            entry_point="web_tools",
            capabilities=["web_search", "web_fetch", "summarize"],
        )

    def get_tools(self) -> List[Tool]:
        return [
            WebSearchTool(),
            FetchUrlTool(),
            SummarizeTool(),
        ]


DDG_API_URL = "https://api.duckduckgo.com/?format=json&no_html=1&skip_disambiguation=1&q="


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web using DuckDuckGo"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)

        if not query.strip():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Empty query",
            )

        try:
            url = DDG_API_URL + quote_plus(query.strip())
            request = Request(url, headers={"User-Agent": "JARVIS/1.0"})

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: urlopen(request, timeout=10))
            data = json.loads(response.read().decode("utf-8"))

            results = []

            if data.get("Abstract"):
                results.append({
                    "title": data.get("AbstractSource", "DuckDuckGo"),
                    "snippet": data["Abstract"],
                    "url": data.get("AbstractURL", ""),
                })

            for topic in data.get("RelatedTopics", []):
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("FirstURL", "Related").split("/")[-1] or "Related",
                        "snippet": topic["Text"],
                        "url": topic.get("FirstURL", ""),
                    })

            for result in data.get("Results", []):
                if isinstance(result, dict) and result.get("Content"):
                    results.append({
                        "title": result.get("Title", ""),
                        "snippet": result["Content"],
                        "url": result.get("FirstURL", ""),
                    })

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"results": results[:max_results], "query": query},
            )

        except HTTPError as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=f"HTTP error {e.code}",
            )
        except URLError:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Could not reach search service",
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = "Fetch content from a URL"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "timeout": {"type": "integer", "default": 10},
        },
        "required": ["url"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        url = arguments["url"]
        timeout = arguments.get("timeout", 10)

        try:
            request = Request(url, headers={"User-Agent": "JARVIS/1.0"})
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: urlopen(request, timeout=timeout))
            content = response.read().decode("utf-8", errors="replace")

            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"url": url, "content": content[:10000], "length": len(content)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )


class SummarizeTool(Tool):
    name = "summarize"
    description = "Summarize text content using LLM"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to summarize"},
            "max_sentences": {"type": "integer", "default": 3},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: Dict[str, Any], context: Context) -> ToolResult:
        from ollama import AsyncClient
        settings = get_settings()

        text = arguments["text"]
        max_sentences = arguments.get("max_sentences", 3)

        if not text.strip():
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error="Empty text",
            )

        try:
            client = AsyncClient(host=settings.models.ollama_host)
            response = await client.chat(
                model=settings.models.chat_model,
                messages=[{
                    "role": "user",
                    "content": f"Summarize in {max_sentences} sentences. Be concise.\n\n{text}"
                }],
                options={"temperature": 0.3},
            )

            summary = response.get("message", {}).get("content", "").strip()
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.SUCCESS,
                result={"summary": summary, "original_length": len(text)},
            )
        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                status=ToolResultStatus.ERROR,
                error=str(e),
            )
