import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from config import TAVILY_API_KEY

TAVILY_URL = "https://api.tavily.com/search"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Returns [{content, url}, ...]. Raises after 3 retries with exponential
    backoff so the caller (gatherer_web_node) can catch it and fall back
    gracefully instead of looping."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TAVILY_URL,
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results, "include_answer": False},
        )
        resp.raise_for_status()  # 429/5xx -> HTTPStatusError -> retried above
        data = resp.json()
        return [{"content": r["content"], "url": r["url"]} for r in data.get("results", [])]
