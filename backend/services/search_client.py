import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import TAVILY_API_KEY
from services.llm_client import LLMError

logger = logging.getLogger("search")

TAVILY_URL = "https://api.tavily.com/search"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
async def _search_web_raw(query: str, max_results: int = 5) -> list[dict]:
    """Raw Tavily call with the original 3x exponential-backoff retry.
    Kept intact — this is the retry that was already working. On 429/5xx the
    raise_for_status() below triggers a retry; after 3 attempts it re-raises."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TAVILY_URL,
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results, "include_answer": False},
        )
        resp.raise_for_status()  # 429/5xx -> HTTPStatusError -> retried above
        data = resp.json()
        return [{"content": r["content"], "url": r["url"]} for r in data.get("results", [])]


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Public entry point. Runs the retrying raw call, then normalises any
    final failure into the shared LLMError shape so the rest of the app
    handles web and LLM failures identically. Raw errors are logged only."""
    try:
        return await _search_web_raw(query, max_results=max_results)
    except Exception as exc:
        logger.exception("web search failed")
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            raise LLMError(429, "web_search_error", "Web Search Rate Limited",
                           "Web search hit its rate limit. Please try again shortly.", True) from exc
        raise LLMError(502, "web_search_error", "Web Search Failed",
                       "Web search is currently unavailable.", True) from exc
