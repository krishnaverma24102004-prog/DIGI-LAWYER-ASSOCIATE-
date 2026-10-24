"""Live web search for the external-researcher agent (Tavily).

Used when the firm's knowledge base has nothing (or nothing confident) for the matter:
recent legal news, public case law and updated statutes.

Privacy: queries never contain client details. They are written by Claude from the
masked case facts with instructions to generalize (no names, places, dates of birth or
identifiers), and only those generic queries are sent to the search provider.

Results are untrusted public content. They are given to the agents as reference
material they are told not to take instructions from, and every source is shown to the
user with its URL so it can be checked.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 1200


class WebSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str
    score: float
    query: str
    published_date: str | None = None

    def source(self) -> dict:
        """What the client is shown."""
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet[:400],
            "published_date": self.published_date,
            "score": round(self.score, 3),
        }

    def as_dict(self) -> dict:
        return asdict(self)


def is_configured() -> bool:
    settings = get_settings()
    return settings.web_search_enabled and bool(settings.tavily_api_key)


_client = None


def _get_client(http_client: httpx.AsyncClient | None = None):
    global _client
    from tavily import AsyncTavilyClient

    if http_client is not None:
        return AsyncTavilyClient(api_key=get_settings().tavily_api_key, client=http_client)
    if _client is None:
        settings = get_settings()
        if not settings.tavily_api_key:
            raise WebSearchError("TAVILY_API_KEY is not set")
        _client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    return _client


async def search_web(queries: list[str], *, max_results: int | None = None, http_client: httpx.AsyncClient | None = None) -> list[WebResult]:
    """Run the queries concurrently; return de-duplicated results, best first."""
    settings = get_settings()
    max_results = max_results or settings.web_search_max_results
    queries = [q.strip()[:400] for q in queries if q and q.strip()][:3]
    if not queries:
        return []
    client = _get_client(http_client)
    domains = settings.web_search_domain_list

    async def one(query: str) -> list[WebResult]:
        kwargs = {"search_depth": "basic", "topic": "general", "max_results": max_results}
        if domains:
            kwargs.update(include_domains=domains, include_domains_mode="prefer")
        response = await client.search(query, **kwargs)
        return [
            WebResult(
                title=(item.get("title") or item.get("url") or "Untitled").strip()[:300],
                url=item["url"],
                snippet=(item.get("content") or "").strip()[:SNIPPET_CHARS],
                score=float(item.get("score") or 0.0),
                query=query,
                published_date=item.get("published_date"),
            )
            for item in response.get("results", [])
            if item.get("url", "").startswith(("https://", "http://"))
        ]

    batches = await asyncio.gather(*(one(q) for q in queries), return_exceptions=True)
    best: dict[str, WebResult] = {}
    failures = 0
    for batch in batches:
        if isinstance(batch, Exception):
            failures += 1
            logger.warning("Web search query failed: %s", batch)
            continue
        for result in batch:
            if result.url not in best or result.score > best[result.url].score:
                best[result.url] = result
    if failures == len(queries):
        raise WebSearchError("Web search failed")
    return sorted(best.values(), key=lambda r: r.score, reverse=True)[:max_results]
