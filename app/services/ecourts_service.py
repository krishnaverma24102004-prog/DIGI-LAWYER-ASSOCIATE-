"""Court case tracking: case status and hearing dates by CNR, and hearing reminders.

There is no official public eCourts developer API (the eCourts portal is captcha-protected, and
we don't work around that). Case data comes from the eCourtsIndia API (a commercial provider of
eCourts data, https://ecourtsindia.com/api) when ECOURTS_API_KEY is set; otherwise cases are
tracked with dates the lawyer enters, and everything else (agenda, reminders) works the same.
"""

import logging
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TABLE = "court_cases"
CNR = re.compile(r"^[A-Z0-9]{16}$")


class CaseDataError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().ecourts_api_key)


def normalize_cnr(value: str | None) -> str | None:
    if not value:
        return None
    cnr = re.sub(r"[\s-]", "", value).upper()
    if not CNR.match(cnr):
        raise ValueError("A CNR is 16 letters and digits, e.g. MHPU010012342024")
    return cnr


def _date(value) -> str | None:
    """Provider dates come as YYYY-MM-DD or DD-MM-YYYY (sometimes with a time)."""
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _strings(values) -> list[str]:
    return [" ".join(str(v).split()) for v in (values or []) if str(v).strip()][:20]


def from_provider(payload: dict) -> dict:
    """The eCourtsIndia case record as court_cases columns."""
    data = payload.get("data") or {}
    case = data.get("courtCaseData") or {}
    info = data.get("entityInfo") or {}
    petitioners, respondents = _strings(case.get("petitioners")), _strings(case.get("respondents"))
    title = f"{petitioners[0]} v. {respondents[0]}" if petitioners and respondents else (case.get("caseNumber") or "Court case")
    return {
        "title": title[:300],
        "court_name": case.get("courtName"),
        # "CC 2/2026" as lawyers write it; the provider's caseNumber is an internal 15-digit id.
        "case_number": (f"{case['caseType']} {case['registrationNumber']}" if case.get("caseType") and case.get("registrationNumber")
                        else case.get("caseNumber")),
        "case_status": case.get("caseStatus"),
        "petitioners": petitioners,
        "respondents": respondents,
        "next_hearing_date": _date(case.get("nextHearingDate") or info.get("nextDateOfHearing")),
        "last_hearing_date": _date(case.get("lastHearingDate") or info.get("lastDateOfHearing")),
        "source": "ecourtsindia",
        "provider_data": {
            "judges": case.get("judges"),
            "orders": [
                {"date": _date(o.get("orderDate")), "url": o.get("orderUrl")}
                for o in [*(case.get("interimOrders") or []), *(case.get("judgmentOrders") or [])]
                if isinstance(o, dict)
            ][:50],
            "hearings": (case.get("historyOfCaseHearings") or [])[:50],
        },
    }


async def fetch_case(cnr: str, *, http_client: httpx.AsyncClient | None = None) -> dict:
    settings = get_settings()
    if not settings.ecourts_api_key:
        raise CaseDataError("Case data is not configured (ECOURTS_API_KEY)")
    headers = {"Authorization": f"Bearer {settings.ecourts_api_key}"}
    url = f"{settings.ecourts_base_url.rstrip('/')}/api/partner/case/{cnr}"
    client = http_client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise CaseDataError(f"Could not reach the case data provider ({type(exc).__name__})") from exc
    finally:
        if http_client is None:
            await client.aclose()
    if response.status_code == 404:
        raise CaseDataError("No case with this CNR")
    if response.status_code >= 400:
        raise CaseDataError(f"Case data provider error {response.status_code}")
    return from_provider(response.json())


async def sync(db, case: dict, *, http_client: httpx.AsyncClient | None = None) -> dict:
    """Refresh one case from the provider; a failure is recorded on the case, not raised."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        fields = await fetch_case(case["cnr"], http_client=http_client)
        fields.pop("title")  # the case keeps the title it was given
        update = {**fields, "last_synced_at": now, "sync_error": None}
    except CaseDataError as exc:
        update = {"last_synced_at": now, "sync_error": str(exc)}
    rows = await run_in_threadpool(lambda: db.table(TABLE).update(update).eq("id", case["id"]).execute().data)
    return rows[0] if rows else {**case, **update}


def agenda(cases: list[dict], today: date, days: int) -> list[dict]:
    """Cases with a hearing from today to `days` ahead, soonest first."""
    end = today + timedelta(days=days)
    upcoming = [c for c in cases if c.get("next_hearing_date") and today.isoformat() <= c["next_hearing_date"] <= end.isoformat()]
    return sorted(upcoming, key=lambda c: c["next_hearing_date"])


def needs_reminder(case: dict, today: date, days: int) -> bool:
    """A client reminder is due: a hearing within `days`, a phone number, and not reminded for this date yet."""
    hearing = case.get("next_hearing_date")
    return bool(
        case.get("client_phone") and hearing
        and today.isoformat() <= hearing <= (today + timedelta(days=days)).isoformat()
        and case.get("reminded_for_date") != hearing
    )
