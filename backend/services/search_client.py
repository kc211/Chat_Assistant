import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import SERPER_API_KEY
from services.llm_client import LLMError

logger = logging.getLogger("search")
SERPER_URL = "https://google.serper.dev/search"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
async def _search_web_raw(query: str, max_results: int = 5) -> list[dict]:
   
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "num": max_results}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(SERPER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        
        results = data.get("organic") or []
        out = []
        for r in results[:max_results]:
            content = r.get("snippet") or r.get("title") or ""
            url = r.get("link") or ""
            if content and url:
                out.append({"content": content, "url": url})
        return out


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Public entry point. Runs the retrying raw call, then normalises any
    final failure into the shared LLMError shape so web and LLM failures are
    handled identically upstream. Raw errors are logged only."""
    try:
        return await _search_web_raw(query, max_results=max_results)
    except Exception as exc:
        logger.exception("web search failed")
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            raise LLMError(429, "web_search_error", "Web Search Rate Limited",
                           "Web search hit its rate limit. Please try again shortly.", True) from exc
        if status in (401, 403):
            raise LLMError(401, "web_search_error", "Web Search Auth Failed",
                           "Web search authentication failed. Please verify the search API key.", False) from exc
        raise LLMError(502, "web_search_error", "Web Search Failed",
                       "Web search is currently unavailable.", True) from exc