import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import BRAVE_API_KEY
from services.llm_client import LLMError

logger = logging.getLogger("search")

# Brave Web Search API. Returns blue-link results with description/url, which
# we normalise to the same {content, url} shape the rest of the app expects,
# so gatherer_web_node / gatherer_both_node need no changes.
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
async def _search_web_raw(query: str, max_results: int = 5) -> list[dict]:
    """Raw Brave call with 3x exponential-backoff retry. The backoff also
    absorbs Brave's free-tier 1 req/sec rate limit (429), which
    raise_for_status() turns into an HTTPStatusError that triggers a retry."""

    print("inside the search query function------")
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
    params = {"q": query, "count": max_results}  # Brave caps count at 20
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(BRAVE_URL, headers=headers, params=params)
        resp.raise_for_status()  # 429/5xx -> HTTPStatusError -> retried above
        data = resp.json()

        print("-----------------")
        print(data)

        results = (data.get("web") or {}).get("results") or []
        out = []
        for r in results[:max_results]:
            content = r.get("description") or r.get("title") or ""
            url = r.get("url") or ""
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
        if status == 401:
            raise LLMError(401, "web_search_error", "Web Search Auth Failed",
                           "Web search authentication failed. Please verify the search API key.", False) from exc
        raise LLMError(502, "web_search_error", "Web Search Failed",
                       "Web search is currently unavailable.", True) from exc
