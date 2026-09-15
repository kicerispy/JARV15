"""
JARVIS web search and summarization tools.
"""
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from ollama import chat

from config import CHAT_MODEL
from logger import logger


DuckDuckGo_URL = "https://duckduckgo.com/?q="
DDG_API_URL = "https://api.duckduckgo.com/?format=json&no_html=1&skip_disambiguation=1&q="


def _http_get_json(url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Perform an HTTP GET and parse JSON response."""
    request = Request(url, headers={"User-Agent": "JARVIS/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError) as e:
        logger.warning(f"HTTP request failed: {e}")
        return None


def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Search the web using DuckDuckGo.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.

    Returns:
        List of result dicts with 'title', 'snippet', and 'url' keys.
    """
    if not query or not query.strip():
        return []

    url = DDG_API_URL + quote_plus(query.strip())
    data = _http_get_json(url)

    if not data:
        return []

    results: List[Dict[str, str]] = []

    # Instant answers
    if data.get("Abstract"):
        results.append({
            "title": data.get("AbstractSource", "DuckDuckGo"),
            "snippet": data["Abstract"],
            "url": data.get("AbstractURL", ""),
        })

    # Related topics
    for topic in data.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("Text"):
            results.append({
                "title": topic.get("FirstURL", "Related").split("/")[-1] or "Related",
                "snippet": topic["Text"],
                "url": topic.get("FirstURL", ""),
            })

    # Results
    for result in data.get("Results", []):
        if isinstance(result, dict) and result.get("Content"):
            results.append({
                "title": result.get("Title", ""),
                "snippet": result["Content"],
                "url": result.get("FirstURL", ""),
            })

    return results[:max_results]


def summarize_web_results(results: List[Dict[str, str]]) -> str:
    """
    Summarize web search results using the LLM.

    Args:
        results: List of search result dicts.

    Returns:
        A concise summary string.
    """
    if not results:
        return "I found no results for that search."

    if len(results) == 1:
        r = results[0]
        return f"{r['snippet']} Source: {r['url']}"

    # Build context for summarization
    context = "\n\n".join(
        f"Title: {r.get('title', '')}\nSnippet: {r.get('snippet', '')}\nURL: {r.get('url', '')}"
        for r in results
    )

    prompt = f"""Summarize these search results in 2-3 sentences. Be concise.

{context}"""

    try:
        response = chat(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3}
        )
        summary = response.get("message", {}).get("content", "").strip()
        return summary or "I couldn't summarize the results."
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")
        # Fallback: return first result
        return results[0].get("snippet", "No results found.")