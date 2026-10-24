"""Indian Kanoon API (https://api.indiankanoon.org): Indian case-law search.

Used for:
  * citation checks: a case the agents cite that the Supreme Court index doesn't know (most High
    Court and tribunal cases) is looked up by its parties' names before it is marked unverified;
  * case-law search for lawyers (`GET /api/v1/caselaw/search`).

The API is prepaid per call (search Rs 0.50 at the time of writing), so lookups are capped per
check and remembered for the life of the process. Its terms allow use in RAG products with
"powered by IKanoon" attribution in a prominent place (the About page).
"""

import html
import logging
import re
from functools import lru_cache

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

BASE = "https://api.indiankanoon.org"
MAX_LOOKUPS_PER_CHECK = 3
ATTRIBUTION = "Case law search powered by IKanoon (indiankanoon.org)"


class IndianKanoonError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().indiankanoon_api_token)


def _clean(text: str | None) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def search(query: str, *, page: int = 0, doctypes: str | None = None, title: str | None = None,
           client: httpx.Client | None = None) -> list[dict]:
    """One page of results: [{tid, title, court, headline, url}]. Blocking."""
    token = get_settings().indiankanoon_api_token
    if not token:
        raise IndianKanoonError("Indian Kanoon is not configured (INDIANKANOON_API_TOKEN)")
    params = {"formInput": query, "pagenum": page}
    if doctypes:
        params["doctypes"] = doctypes
    if title:
        params["title"] = title
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        response = client.post(f"{BASE}/search/", params=params, headers={"Authorization": f"Token {token}", "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise IndianKanoonError(f"Could not reach Indian Kanoon ({type(exc).__name__})") from exc
    finally:
        if own:
            client.close()
    if response.status_code >= 400:
        raise IndianKanoonError(f"Indian Kanoon error {response.status_code}")
    return [
        {
            "tid": d.get("tid"),
            "title": _clean(d.get("title")),
            "court": d.get("docsource"),
            "headline": _clean(d.get("headline"))[:400],
            "url": f"https://indiankanoon.org/doc/{d.get('tid')}/",
        }
        for d in response.json().get("docs") or []
    ]


@lru_cache(maxsize=2048)
def case_exists(name_tokens: tuple[str, ...]) -> bool:
    """Whether a judgment whose title has all these party-name words exists. Blocking; cached."""
    from app.services.citation_service import _name_tokens

    try:
        results = search(" ANDD ".join(name_tokens), title=" ".join(name_tokens))
    except IndianKanoonError as exc:
        logger.warning("Indian Kanoon lookup failed: %s", exc)
        raise  # not cached: lru_cache keeps results, not exceptions
    wanted = set(name_tokens)
    return any(wanted <= set(_name_tokens(r["title"])) for r in results)


def find_cases(names: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    """The names (at most MAX_LOOKUPS_PER_CHECK, of two or more words) Indian Kanoon has a judgment for."""
    found = []
    for tokens in [n for n in dict.fromkeys(names) if len(n) >= 2][:MAX_LOOKUPS_PER_CHECK]:
        try:
            if case_exists(tokens):
                found.append(tokens)
        except IndianKanoonError:
            break  # out of credit or unreachable: stop for this check
    return found
