"""Nightly cause-list reconciliation (P05): ingest lists, match them to the firm's matters, escalate.

What it does, deterministically (no AI anywhere in parsing or matching):

1. **Ingest** a cause-list PDF (fetched from a court website that allows it, or forwarded by a firm
   member): pypdfium2 text with positions, Tesseract for scanned pages (never the vision fallback),
   then the court's grammar (``app/services/causelists/<court>.py``). Each list is stored with its
   source URL and SHA-256; a revised list at the same URL (new hash) supersedes the old one, and only
   matters whose listing changed are notified again.
2. **Match** each organization's tracked matters (``court_cases``) against the items: case-type
   aliases plus normalised number/year give *exact* matches; parties (token overlap) plus the
   matter's advocate give *probable* ones; any other item naming a firm advocate (roster in
   ``advocate_aliases`` plus members' names, with enrolment / AOR codes) is *possibly ours*.
   Only exact matches in daily or supplementary lists set ``next_hearing_date``; advance-list
   matches are shown as expected; probable ones need a click.
3. **Escalate** unconfirmed listings, on a clock that starts when the list was ingested: amber
   (to the fallback advocate) at the later of 20:00 IST the evening before and ingestion + 1 h,
   red (to partners) at the later of 21:00 and ingestion + 2 h, and again at 07:30 on the day.
4. **Warn** on matters whose last hearing passed more than 3 days ago with no order in the provider
   data, and on matters shown disposed with no judgment online (limitation is then provisional).

Server-side jobs (service role), each scoped to one organization at a time (CLAUDE.md invariant 2
needs these added): ``fetch_and_ingest`` (cron every 30 min, 17:00-10:00 IST) and ``escalate``
(cron every 15 min, 19:00-22:30 and 07:30 IST). Notifications are the listing_matches rows the
board shows, plus an n8n ``listing-escalation`` webhook when configured; payloads carry case numbers,
never party names.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

import httpx
from fastapi.concurrency import run_in_threadpool

from app.services import audit_service, causelists, n8n_service
from app.services.causelists import CaseKey, case_key, name_tokens, parse_case_text, type_key

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
AMBER_AT = time(20, 0)
RED_AT = time(21, 0)
MORNING_AT = time(7, 30)
AMBER_AFTER = timedelta(hours=1)
RED_AFTER = timedelta(hours=2)
ORDER_LAG_DAYS = 3
MAX_PDF_BYTES = 25 * 1024 * 1024
MIN_ITEMS_PER_PAGE = 0.5        # below this a multi-page list is probably mis-parsed (anomaly alert)
PROBABLE_PARTIES = 0.6          # share of the shorter party-token set that must match
PROBABLE_WITH_ADVOCATE = 0.4    # ... when the matter's advocate is also named on the item
N8N_PATH = "listing-escalation"
LISTED_TYPES = ("daily", "supplementary")

PARTY_STOPWORDS = {
    "AND", "ORS", "ANR", "OTHERS", "ANOTHER", "THE", "OF", "VS", "V", "VERSUS", "M/S", "MS", "MR", "MRS", "SH", "SMT",
    "DR", "THROUGH", "THR", "LRS", "LR", "LTD", "PVT", "PRIVATE", "LIMITED", "CO", "STATE", "UNION", "INDIA", "GOVT",
    "GOVERNMENT", "NCT", "SECRETARY", "ITS", "BY", "IN", "FOR", "TO", "DEAD", "SINCE", "NOW",
}
DISPOSED = re.compile(r"\bdisposed\b|\bdecided\b|\bdismissed\b|\ballowed\b", re.IGNORECASE)


class CauseListError(ValueError):
    pass


# ============================================================================ time


def ist(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST)


def _parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _as_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def in_polling_window(config: causelists.FetcherConfig, now: datetime) -> bool:
    clock = ist(now).time()
    if config.poll_start <= config.poll_end:
        return config.poll_start <= clock < config.poll_end
    return clock >= config.poll_start or clock < config.poll_end


def board_date(now: datetime) -> date:
    """'Tonight's board' is for tomorrow; in the morning it is today's."""
    local = ist(now)
    return local.date() + timedelta(days=1) if local.time() >= time(12, 0) else local.date()


def due_level(ingested_at, list_date: date, now: datetime) -> int:
    """Escalation level due now: 1 amber (fallback), 2 red (partners), 3 the 07:30 call on the day.

    The clock runs from ingestion, so a supplementary list published at 23:00 still gets its hour
    before anyone is chased."""
    ingested = ist(_parse_ts(ingested_at))
    local = ist(now)
    evening = list_date - timedelta(days=1)
    amber = max(datetime.combine(evening, AMBER_AT, IST), ingested + AMBER_AFTER)
    red = max(datetime.combine(evening, RED_AT, IST), ingested + RED_AFTER)
    morning = datetime.combine(list_date, MORNING_AT, IST)
    level = 0
    if local >= amber:
        level = 1
    if local >= red:
        level = 2
    if local >= morning and ingested < morning:
        level = 3
    return level


# ============================================================================ warnings (order lag)


def _orders(case: dict) -> list[date]:
    data = case.get("provider_data") or {}
    out = []
    for order in data.get("orders") or []:
        if isinstance(order, dict) and (day := _as_date(order.get("date"))):
            out.append(day)
    return out


def disposed_without_judgment(case: dict) -> bool:
    """Shown disposed, but no order or judgment on or after the last hearing is online: any
    limitation computed from the disposal is provisional and should use the safe date."""
    if not DISPOSED.search(case.get("case_status") or ""):
        return False
    last = _as_date(case.get("last_hearing_date"))
    orders = _orders(case)
    return not orders or (last is not None and not any(o >= last for o in orders))


def case_warnings(case: dict, today: date) -> list[dict]:
    warnings = []
    last = _as_date(case.get("last_hearing_date"))
    if last and last <= today and (today - last).days > ORDER_LAG_DAYS and not any(o >= last for o in _orders(case)):
        warnings.append({"kind": "order_lag", "message": f"last hearing {last.day} {last.strftime('%b')}, order not uploaded yet"})
    if disposed_without_judgment(case):
        warnings.append({"kind": "disposed_no_judgment",
                         "message": "shown disposed with no judgment online: limitation is provisional"})
    return warnings


# ============================================================================ matching (pure)


def court_compatible(court_name: str | None, court_code: str) -> bool | None:
    """True / False when the matter's court is recognisably this court or another; None when unknown."""
    if not court_name or not court_name.strip():
        return None
    module = causelists.get_parser(court_code)
    pattern = getattr(module, "COURT_NAMES", None)
    if pattern is None:
        return None
    return bool(pattern.search(court_name))


def party_tokens(*texts) -> set[str]:
    words = set()
    for text in texts:
        if isinstance(text, (list, tuple)):
            words |= party_tokens(*text)
            continue
        for word in re.sub(r"[^A-Z0-9/ ]", " ", str(text or "").upper()).split():
            if len(word) >= 2 and word not in PARTY_STOPWORDS and not word.isdigit():
                words.add(word)
    return words


def party_score(case_words: set[str], item_words: set[str]) -> tuple[float, set[str]]:
    shared = case_words & item_words
    smaller = min(len(case_words), len(item_words))
    if smaller < 2 or len(shared) < 2:
        return 0.0, shared
    return len(shared) / smaller, shared


def _alias_match(alias_words: list[str], advocate: str) -> bool:
    """Every word of the alias appears in the printed name; an initial matches a word's first letter."""
    words = name_tokens(advocate)
    if len([w for w in alias_words if len(w) > 1]) < 2 or not words:
        return False
    pool = list(words)
    for word in alias_words:
        if word in pool:
            pool.remove(word)
        elif len(word) == 1 and (hit := next((w for w in pool if w.startswith(word)), None)):
            pool.remove(hit)
        else:
            return False
    return True


class Roster:
    """A firm's matters, advocates and members, as the matcher needs them."""

    def __init__(self, org_id: str, cases: list[dict], aliases: list[dict], members: list[dict], names: dict[str, str],
                 type_aliases: dict[str, str] | None = None):
        self.org_id = org_id
        self.cases = cases
        self.members = {m["user_id"]: m["role"] for m in members}
        self.type_aliases = type_aliases
        entries = [(a["user_id"], a["alias"], a.get("enrolment_no")) for a in aliases]
        entries += [(uid, name, None) for uid, name in names.items() if uid in self.members and name]
        self.aliases = [(uid, alias, name_tokens(alias), (code or "").strip().upper() or None) for uid, alias, code in entries]
        self.case_keys: dict[str, CaseKey | None] = {c["id"]: parse_case_text(c.get("case_number"), type_aliases) for c in cases}
        self.case_words = {c["id"]: party_tokens(c.get("title"), c.get("petitioners") or [], c.get("respondents") or [])
                           for c in cases}

    def partners(self) -> list[str]:
        partners = [u for u, r in self.members.items() if r == "partner"]
        return partners or [u for u, r in self.members.items() if r == "owner"]

    def advocates_named(self, item: dict) -> list[tuple[str, str]]:
        """(user_id, why) for each firm advocate named on the item."""
        found = []
        codes = {str(c).strip().upper() for c in item.get("advocate_codes") or []}
        for user_id, alias, words, code in self.aliases:
            if code and code in codes:
                found.append((user_id, f"{alias} (code {code})"))
            elif any(_alias_match(words, printed) for printed in item.get("advocates") or []):
                found.append((user_id, alias))
        seen, unique = set(), []
        for user_id, why in found:
            if user_id not in seen:
                seen.add(user_id)
                unique.append((user_id, why))
        return unique


def item_key(item: dict, type_aliases=None) -> CaseKey | None:
    return case_key(item.get("case_type"), item.get("case_number"), item.get("case_year"), type_aliases)


def _label(item: dict) -> str:
    if not item.get("case_number"):
        return item.get("case_type") or "?"
    return f"{item.get('case_type')} {item.get('case_number')}/{item.get('case_year')}"


def match_items(items: list[dict], roster: Roster, court_code: str) -> list[dict]:
    """Exact, then probable, then 'possibly ours'. Pure: returns match dicts (no ids or state)."""
    cases = [c for c in roster.cases if court_compatible(c.get("court_name"), court_code) is not False]
    by_key: dict[tuple[str, int], list[dict]] = {}
    for case in cases:
        if (key := roster.case_keys.get(case["id"])):
            by_key.setdefault((key.type_key, key.year), []).append(case)
    matches: list[dict] = []
    exact_cases: set[str] = set()
    unmatched: list[dict] = []
    for item in items:
        key = item_key(item, roster.type_aliases)
        hits = []
        if key:
            for case in by_key.get((key.type_key, key.year), []):
                ck = roster.case_keys[case["id"]]
                if key.covers(ck) or ck.covers(key):
                    hits.append(case)
        for case in hits:
            exact_cases.add(case["id"])
            matches.append({"item": item, "court_case_id": case["id"], "match_type": "exact",
                            "reason": f"Case type, number and year match ({case.get('case_number')} = {_label(item)})",
                            "appearing_advocate_id": case.get("user_id"), "fallback_advocate_id": case.get("fallback_advocate_id")})
        if not hits:
            unmatched.append(item)

    # Probable: parties (and the matter's advocate) match, but not the number.
    index: dict[str, list[dict]] = {}
    for case in cases:
        if case["id"] in exact_cases:
            continue
        for word in roster.case_words[case["id"]]:
            index.setdefault(word, []).append(case)
    still: list[dict] = []
    for item in unmatched:
        words = party_tokens(item.get("parties"))
        named = roster.advocates_named(item)
        named_ids = {u for u, _ in named}
        candidates = {c["id"]: c for w in words for c in index.get(w, [])}
        best = None
        for case in candidates.values():
            score, shared = party_score(roster.case_words[case["id"]], words)
            advocate = case.get("user_id") in named_ids
            if score >= PROBABLE_PARTIES or (advocate and score >= PROBABLE_WITH_ADVOCATE):
                rank = (score + (0.2 if advocate else 0), len(shared))
                if best is None or rank > best[0]:
                    best = (rank, case, score, shared, advocate)
        if best:
            _, case, score, shared, advocate = best
            reason = (f"Parties match ({', '.join(sorted(shared)[:4])}; {round(score * 100)}%)"
                      + ("; the matter's advocate is named" if advocate else "")
                      + f"; number differs ({_label(item)} vs {case.get('case_number') or 'no number on the matter'})")
            matches.append({"item": item, "court_case_id": case["id"], "match_type": "probable", "reason": reason,
                            "appearing_advocate_id": case.get("user_id"), "fallback_advocate_id": case.get("fallback_advocate_id")})
            continue
        still.append((item, named))

    for item, named in still:
        if named:
            names = ", ".join(why for _, why in named[:3])
            matches.append({"item": item, "court_case_id": None, "match_type": "possibly_ours",
                            "reason": f"Names a firm advocate ({names}) but matches no tracked matter",
                            "appearing_advocate_id": named[0][0], "fallback_advocate_id": None})
    return matches


def match_key(match: dict, item: dict) -> tuple:
    if match.get("court_case_id"):
        return ("case", match["court_case_id"])
    return ("item", item.get("case_type_key"), item.get("case_number"), item.get("case_year"), item.get("item_no"))


# ============================================================================ database helpers


def _q(fn):
    return run_in_threadpool(fn)


async def _select(db, table: str, columns: str = "*", **filters) -> list[dict]:
    def run():
        query = db.table(table).select(columns)
        for name, value in filters.items():
            if name.endswith("__in"):
                query = query.in_(name[:-4], list(value))
            elif name.endswith("__is"):
                query = query.is_(name[:-4], value)
            else:
                query = query.eq(name, value)
        return query.execute().data or []
    return await _q(run)


async def type_aliases(db, court_code: str | None = None) -> dict[str, str]:
    table = dict(causelists.DEFAULT_CASE_TYPE_ALIASES)
    try:
        rows = await _select(db, "case_type_aliases", "court_code, alias, canonical")
    except Exception:
        logger.warning("case_type_aliases unavailable; using the built-in table", exc_info=True)
        rows = []
    for row in sorted(rows, key=lambda r: r.get("court_code") is not None):  # court-specific rows win
        if row.get("court_code") in (None, court_code):
            table[type_key(row["alias"], {})] = type_key(row["canonical"], {})
    return table


async def ensure_court(admin_db, config: causelists.FetcherConfig) -> None:
    row = {"code": config.court_code, "name": config.name, "complex": config.complex, "state": config.state,
           "source_url": config.home_url}
    await _q(lambda: admin_db.table("courts").upsert(row, on_conflict="code", ignore_duplicates=True).execute())


async def load_roster(admin_db, org_id: str, aliases: dict[str, str]) -> Roster:
    """Everything the matcher needs for one organization (service role, scoped to that org)."""
    cases = await _select(admin_db, "court_cases",
                          "id, org_id, user_id, title, court_name, case_number, petitioners, respondents, next_hearing_date, "
                          "fallback_advocate_id", org_id=org_id)
    alias_rows = await _select(admin_db, "advocate_aliases", "user_id, alias, enrolment_no", org_id=org_id)
    members = await _select(admin_db, "organization_members", "user_id, role", org_id=org_id)
    names = {}
    if members:
        users = await _select(admin_db, "users", "id, full_name", id__in=[m["user_id"] for m in members])
        names = {u["id"]: u.get("full_name") for u in users}
    return Roster(org_id, cases, alias_rows, members, names, aliases)


async def _orgs_to_match(admin_db) -> list[str]:
    rows = await _select(admin_db, "court_cases", "org_id")
    rows += await _select(admin_db, "advocate_aliases", "org_id")
    return sorted({r["org_id"] for r in rows if r.get("org_id")})


# ============================================================================ notifications


def _payload(event: str, match: dict, item: dict, recipients: list[str], level: int | None = None) -> dict:
    """What leaves the server: where and when the matter is listed and who must act. No party names."""
    return {
        "event": event,
        "org_id": match["org_id"],
        "match_id": match.get("id"),
        "match_type": match.get("match_type"),
        "court_code": item.get("court_code"),
        "courtroom": item.get("courtroom"),
        "item_no": item.get("item_no"),
        "list_date": str(item.get("list_date")),
        "list_type": item.get("list_type"),
        "status": item.get("status"),
        "case": _label(item),
        "escalation_level": match.get("escalation_level") if level is None else level,
        "recipients": [r for r in dict.fromkeys(recipients) if r],
        "board": f"/board?date={item.get('list_date')}",
    }


async def _deliver(payloads: list[dict]) -> None:
    if not payloads or not n8n_service.is_configured():
        return
    for payload in payloads:
        try:
            await n8n_service.trigger_workflow(N8N_PATH, payload)
        except Exception as exc:  # a failed webhook never stops ingestion or escalation
            logger.warning("listing notification not delivered (%s): %s", payload.get("event"), exc)


# ============================================================================ ingestion


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _item_rows(parsed: causelists.ParsedList, list_row: dict, aliases: dict[str, str]) -> list[dict]:
    rows = []
    for seq, item in enumerate(parsed.items):
        rows.append({
            "cause_list_id": list_row["id"],
            "org_id": list_row.get("org_id"),
            "court_code": list_row["court_code"],
            "list_date": list_row["list_date"],
            "list_type": list_row["list_type"],
            "courtroom": item.courtroom,
            "bench_key": item.bench_key,
            "bench_label": item.bench_label,
            "segment": "advance" if list_row["list_type"] == "advance" else item.segment,
            "item_no": item.item_no,
            "position": item.position,
            "connected_to": item.connected_to,
            "status": item.status,
            "case_type": item.case_type,
            "case_type_key": type_key(item.case_type, aliases),
            "case_number": item.case_number,
            "case_year": item.case_year,
            "parties": item.parties,
            "advocates": item.advocates,
            "advocate_codes": item.advocate_codes,
            "page": item.page,
            "seq": seq,
            "fingerprint": causelists.fingerprint(item, list_row["list_type"]),
        })
    return rows


def _anomalies(parsed: causelists.ParsedList) -> list[str]:
    out = []
    if parsed.page_count >= 2 and len(parsed.items) < parsed.page_count * MIN_ITEMS_PER_PAGE and not parsed.deletions:
        out.append(f"only {len(parsed.items)} items on {parsed.page_count} pages: the court may have changed its format")
    unread = sum(1 for i in parsed.items if not i.case_number)
    if unread:
        out.append(f"{unread} item(s) without a readable case number")
    return out


async def ingest_pdf(admin_db, court_code: str, data: bytes, *, now: datetime, source_url: str | None = None,
                     org_id: str | None = None, uploaded_by: str | None = None, filename: str | None = None,
                     list_date: date | None = None, list_type: str | None = None) -> dict:
    """Store and reconcile one list. Public (fetched) when `org_id` is None, else forwarded by that firm."""
    if len(data) > MAX_PDF_BYTES:
        raise CauseListError(f"Cause lists are limited to {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise CauseListError("That is not a PDF")
    module = causelists.get_parser(court_code)
    if module is None:
        raise CauseListError(f"No cause-list parser for {court_code} yet; add the hearing by hand")
    await ensure_court(admin_db, module.FETCHER)  # cause_lists.court_code references courts(code)
    digest = sha256(data)
    if org_id is None:
        same = await _select(admin_db, "cause_lists", "id", source_url=source_url, content_sha256=digest, org_id__is="null")
    else:
        same = await _select(admin_db, "cause_lists", "id", org_id=org_id, court_code=court_code, content_sha256=digest)
    if same:
        return {"status": "unchanged", "cause_list_id": same[0]["id"]}

    try:
        parsed = await run_in_threadpool(causelists.parse_pdf, court_code, data)
    except (ValueError, LookupError) as exc:
        raise CauseListError(str(exc)) from exc
    if list_date and parsed.list_date and parsed.list_date != list_date:
        raise CauseListError(f"This PDF is the list for {parsed.list_date.isoformat()}, not {list_date.isoformat()}")
    day = parsed.list_date or list_date
    if day is None:
        raise CauseListError("The list's date could not be read; give the date it is for")
    kind = parsed.list_type or list_type or "daily"
    warnings = parsed.warnings + _anomalies(parsed)
    for warning in _anomalies(parsed):
        logger.warning("cause list %s %s %s: %s", court_code, day, source_url or filename, warning)

    # The list this one revises: same URL (public) or same file name for the same day (forwarded).
    if org_id is None:
        previous = await _select(admin_db, "cause_lists", "id", source_url=source_url, org_id__is="null", superseded_by__is="null")
    elif filename:
        previous = await _select(admin_db, "cause_lists", "id", org_id=org_id, court_code=court_code, list_date=day.isoformat(),
                                 list_type=kind, filename=filename, superseded_by__is="null")
    else:
        previous = []
    previous_id = previous[0]["id"] if previous else None

    aliases = await type_aliases(admin_db, court_code)
    list_row = {
        "org_id": org_id, "court_code": court_code, "list_date": day.isoformat(), "list_type": kind,
        "source_url": source_url, "content_sha256": digest, "fetched_at": now.astimezone(timezone.utc).isoformat(),
        "source": "fetch" if org_id is None else "forwarded", "uploaded_by": uploaded_by, "filename": filename,
        "parser": court_code, "page_count": parsed.page_count, "item_count": len(parsed.items),
        "parse_warnings": warnings[:50],
    }
    stored = await _q(lambda: admin_db.table("cause_lists").insert(list_row).execute().data[0])
    rows = _item_rows(parsed, stored, aliases)
    items: list[dict] = []
    for start in range(0, len(rows), 500):
        chunk = rows[start:start + 500]
        items += await _q(lambda chunk=chunk: admin_db.table("cause_list_items").insert(chunk).execute().data)
    if previous_id:
        await _q(lambda: admin_db.table("cause_lists").update({"superseded_by": stored["id"]}).eq("id", previous_id).execute())

    notifications: list[dict] = []
    notifications += await apply_deletions(admin_db, court_code, day, parsed.deletions, org_id=org_id, now=now)
    items = await _select(admin_db, "cause_list_items", "*", cause_list_id=stored["id"]) if parsed.deletions else items

    orgs = [org_id] if org_id else await _orgs_to_match(admin_db)
    summary = {"exact": 0, "probable": 0, "possibly_ours": 0, "hearing_dates_set": 0}
    for org in orgs:
        result = await reconcile_org(admin_db, org, stored, items, previous_id, now=now, aliases=aliases)
        notifications += result["notifications"]
        for key in ("exact", "probable", "possibly_ours", "hearing_dates_set"):
            summary[key] += result[key]
    await _deliver(notifications)
    return {"status": "revised" if previous_id else "new", "cause_list_id": stored["id"], "list_date": day.isoformat(),
            "list_type": kind, "items": len(items), "deletions": len(parsed.deletions), "warnings": warnings[:20],
            "notifications": len(notifications), **summary, "_notifications": notifications}


async def apply_deletions(admin_db, court_code: str, day: date, deletions: list, *, org_id: str | None, now: datetime) -> list[dict]:
    """Drop / deletion notes: mark the named items (in any current list for that court and day that
    the note's owner can affect) as deleted, and tell the firms whose matters they were."""
    if not deletions:
        return []
    lists = await _select(admin_db, "cause_lists", "id, org_id", court_code=court_code, list_date=day.isoformat(),
                          superseded_by__is="null")
    list_ids = [row["id"] for row in lists if row.get("org_id") in (None, org_id)]
    if not list_ids:
        return []
    candidates = await _select(admin_db, "cause_list_items", "*", cause_list_id__in=list_ids, status="listed")
    aliases = await type_aliases(admin_db, court_code)
    touched: list[dict] = []
    for deletion in deletions:
        dkey = case_key(deletion.case_type, deletion.case_number, deletion.case_year, aliases)
        for item in candidates:
            if deletion.item_no and item.get("item_no") != deletion.item_no:
                continue
            if deletion.courtroom and item.get("courtroom") != deletion.courtroom:
                continue
            ikey = item_key(item, aliases)
            if dkey and ikey and not (dkey.covers(ikey) or ikey.covers(dkey)):
                continue
            if not dkey and not deletion.courtroom:
                continue  # neither a case number nor a courtroom: too vague to act on
            if item in touched:
                continue
            item["status"] = deletion.status
            item["position"] = None
            touched.append(item)
    notifications = []
    for item in touched:
        await _q(lambda item=item: admin_db.table("cause_list_items").update({"status": item["status"], "position": None})
                 .eq("id", item["id"]).execute())
        matches = await _select(admin_db, "listing_matches", "*", item_id=item["id"])
        for match in matches:
            await _restore_hearing_date(admin_db, match, item)
            notifications.append(_payload("listing.deleted", match, item,
                                          [match.get("appearing_advocate_id"), match.get("fallback_advocate_id")]))
    return notifications


async def _set_hearing_date(admin_db, org_id: str, case: dict, item: dict) -> dict | None:
    """An exact daily/supplementary listing sets the matter's next hearing date. Provider fields are
    server-owned (migration 014): written with the service role, scoped to the case and its org,
    and audited because the firm sees the change."""
    day = item["list_date"] if isinstance(item["list_date"], str) else item["list_date"].isoformat()
    if case.get("next_hearing_date") == day:
        return None
    previous = case.get("next_hearing_date")
    await _q(lambda: admin_db.table("court_cases").update({"next_hearing_date": day})
             .eq("id", case["id"]).eq("org_id", org_id).execute())
    case["next_hearing_date"] = day
    await audit_service.alog_action(None, org_id, "SET_HEARING_FROM_CAUSE_LIST", "court_case", case["id"],
                                    metadata={"list_date": day, "previous": previous,
                                              "court_code": item.get("court_code"), "item_no": item.get("item_no"),
                                              "cause_list_id": item.get("cause_list_id")})
    return {"previous_hearing_date": previous, "hearing_date_set": True}


async def _restore_hearing_date(admin_db, match: dict, item: dict, *, update_match: bool = True) -> None:
    """A listing that set the hearing date was deleted or dropped: put the previous date back,
    unless someone has changed it since."""
    if not match.get("hearing_date_set") or not match.get("court_case_id"):
        return
    rows = await _select(admin_db, "court_cases", "id, next_hearing_date", id=match["court_case_id"], org_id=match["org_id"])
    day = str(item.get("list_date"))
    if not rows or rows[0].get("next_hearing_date") != day:
        return
    previous = match.get("previous_hearing_date")
    await _q(lambda: admin_db.table("court_cases").update({"next_hearing_date": previous})
             .eq("id", match["court_case_id"]).eq("org_id", match["org_id"]).execute())
    if update_match and match.get("id"):
        await _q(lambda: admin_db.table("listing_matches").update({"hearing_date_set": False})
                 .eq("id", match["id"]).eq("org_id", match["org_id"]).execute())
    await audit_service.alog_action(None, match["org_id"], "RESTORE_HEARING_AFTER_CAUSE_LIST", "court_case", match["court_case_id"],
                                    metadata={"list_date": day, "restored": previous, "reason": item.get("status")})


async def set_hearing_after_claim(admin_db, match: dict, item: dict, case: dict) -> bool:
    """A member claimed or confirmed a probable / 'possibly ours' listing for a matter: now (and only
    now) its next hearing date follows the list. The caller has checked the member may see the case."""
    if match.get("hearing_date_set") or not eligible_for_hearing_date({**match, "court_case_id": case["id"]}, item):
        return False
    update = await _set_hearing_date(admin_db, match["org_id"], case, item)
    if not update:
        return False
    await _q(lambda: admin_db.table("listing_matches").update(update).eq("id", match["id"]).eq("org_id", match["org_id"]).execute())
    return True


def eligible_for_hearing_date(match: dict, item: dict) -> bool:
    return (match.get("court_case_id") is not None and item.get("status") == "listed"
            and item.get("list_type") in LISTED_TYPES)


async def reconcile_org(admin_db, org_id: str, list_row: dict, items: list[dict], previous_list_id: str | None, *,
                        now: datetime, aliases: dict[str, str] | None = None) -> dict:
    """Match one list against one firm and store the result; a revision carries over what didn't change."""
    aliases = aliases if aliases is not None else await type_aliases(admin_db, list_row["court_code"])
    roster = await load_roster(admin_db, org_id, aliases)
    cases = {c["id"]: c for c in roster.cases}
    found = match_items(items, roster, list_row["court_code"])

    old_by_key: dict[tuple, tuple[dict, dict]] = {}
    if previous_list_id:
        old_matches = await _select(admin_db, "listing_matches", "*", org_id=org_id, cause_list_id=previous_list_id)
        if old_matches:
            old_items = {i["id"]: i for i in await _select(admin_db, "cause_list_items", "*",
                                                              id__in=[m["item_id"] for m in old_matches])}
            for match in old_matches:
                item = old_items.get(match["item_id"])
                if item:
                    old_by_key[match_key(match, item)] = (match, item)

    stamp = now.astimezone(timezone.utc).isoformat()
    rows, notifications, counts = [], [], {"exact": 0, "probable": 0, "possibly_ours": 0, "hearing_dates_set": 0}
    for found_match in found:
        item = found_match["item"]
        counts[found_match["match_type"]] += 1
        row = {
            "org_id": org_id, "item_id": item["id"], "cause_list_id": list_row["id"], "court_case_id": found_match["court_case_id"],
            "match_type": found_match["match_type"], "reason": found_match["reason"][:500], "state": "open",
            "appearing_advocate_id": found_match["appearing_advocate_id"], "fallback_advocate_id": found_match["fallback_advocate_id"],
            "escalation_level": 0, "ingested_at": stamp, "court_code": list_row["court_code"], "list_date": list_row["list_date"],
            "list_type": list_row["list_type"], "previous_hearing_date": None, "hearing_date_set": False, "notified_at": stamp,
            # Every row carries the same keys (PostgREST bulk inserts take the columns of the first row).
            "confirmed_by": None, "confirmed_at": None, "escalated_at": None,
        }
        old = old_by_key.pop(match_key(row, item), None)
        changed = True
        if old:
            old_match, old_item = old
            for field in ("appearing_advocate_id", "fallback_advocate_id", "previous_hearing_date", "hearing_date_set"):
                row[field] = old_match.get(field)
            if old_item.get("fingerprint") == item.get("fingerprint") and old_match["match_type"] == row["match_type"]:
                changed = False
                for field in ("state", "confirmed_by", "confirmed_at", "escalation_level", "escalated_at", "ingested_at", "notified_at"):
                    row[field] = old_match.get(field)
        if row["match_type"] == "exact" and eligible_for_hearing_date(row, item) and not row["hearing_date_set"]:
            update = await _set_hearing_date(admin_db, org_id, cases[row["court_case_id"]], item)
            if update:
                row.update(update)
                counts["hearing_dates_set"] += 1
        elif row["hearing_date_set"] and not (row["match_type"] == "exact" and eligible_for_hearing_date(row, item)):
            # The revision deleted or dropped the matter: put its previous date back.
            await _restore_hearing_date(admin_db, row, item, update_match=False)
            row["hearing_date_set"] = False
        rows.append((row, item, changed, old is not None))

    stored = []
    if rows:
        stored = await _q(lambda: admin_db.table("listing_matches").insert([r for r, *_ in rows]).execute().data)
    for (row, item, changed, existed), saved in zip(rows, stored or [r for r, *_ in rows]):
        if not changed:
            continue
        if row["match_type"] == "exact" or row["state"] in ("claimed", "confirmed"):
            recipients = [row["appearing_advocate_id"], row["fallback_advocate_id"]]
        else:
            recipients = roster.partners() + [row["appearing_advocate_id"]]
        notifications.append(_payload("listing.changed" if existed else "listing.new", {**row, **saved}, item, recipients))
    for old_match, old_item in old_by_key.values():  # matters no longer in the revised list
        await _restore_hearing_date(admin_db, old_match, {**old_item, "status": "removed"})
        notifications.append(_payload("listing.removed", old_match, old_item,
                                      [old_match.get("appearing_advocate_id"), old_match.get("fallback_advocate_id")]))
    if previous_list_id:
        await _q(lambda: admin_db.table("listing_matches").delete().eq("org_id", org_id).eq("cause_list_id", previous_list_id).execute())
    return {**counts, "notifications": notifications}


# ============================================================================ fetching


# Conditional-request validators (ETag / Last-Modified) per URL, kept by the worker process, so an
# unchanged list costs the court a 304 instead of a full download every 30 minutes.
_VALIDATORS: dict[str, dict[str, str]] = {}


def candidate_urls(config: causelists.FetcherConfig, now: datetime) -> list[tuple[str, str, date]]:
    """The lists worth polling now: today's (until 10:00) and the next two days' daily and supplementary
    lists, and advance lists up to four days ahead."""
    local = ist(now)
    today = local.date()
    days = ([today] if local.time() < config.poll_end else []) + [today + timedelta(days=n) for n in (1, 2)]
    out: list[tuple[str, str, date]] = []
    for day in days:
        out += [(url, kind, day) for url, kind in config.urls_for(day) if kind != "advance"]
    for n in range(1, 5):
        day = today + timedelta(days=n)
        out += [(url, kind, day) for url, kind in config.urls_for(day) if kind == "advance"]
    return list(dict.fromkeys(out))


async def fetch_and_ingest(admin_db, now: datetime | None = None, *, http_client: httpx.AsyncClient | None = None,
                           delay: float | None = None) -> dict:
    """Cron (every 30 min, 17:00-10:00 IST): poll every court whose terms allow automated access,
    ingest new or revised lists, and reconcile them with every firm (one org at a time)."""
    now = now or datetime.now(timezone.utc)
    report: dict = {"skipped": [], "unchanged": 0, "ingested": [], "errors": []}
    client = http_client or httpx.AsyncClient(timeout=60, follow_redirects=False)
    try:
        for module in causelists.parsers().values():
            config = module.FETCHER
            if not config.automated_access_allowed:
                report["skipped"].append({"court": config.court_code, "reason": "the court's terms do not allow automated access"})
                continue
            if not in_polling_window(config, now):
                report["skipped"].append({"court": config.court_code, "reason": "outside the polling window"})
                continue
            await ensure_court(admin_db, config)
            for url, kind, day in candidate_urls(config, now):
                if causelists.is_captcha_url(url):  # never: lists behind a captcha are forward-only
                    report["errors"].append({"url": url, "error": "captcha-protected"})
                    continue
                headers = {"User-Agent": config.user_agent, **_VALIDATORS.get(url, {})}
                try:
                    response = await client.get(url, headers=headers)
                except httpx.HTTPError as exc:
                    report["errors"].append({"url": url, "error": type(exc).__name__})
                    continue
                finally:
                    pause = config.request_delay_seconds if delay is None else delay
                    if pause:
                        await asyncio.sleep(pause)
                if response.status_code == 404:
                    continue
                if response.status_code == 304:
                    report["unchanged"] += 1
                    continue
                if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                    report["errors"].append({"url": url, "error": f"HTTP {response.status_code}"})
                    continue
                try:
                    result = await ingest_pdf(admin_db, config.court_code, response.content, now=now, source_url=url,
                                              list_type=kind, list_date=None)
                except CauseListError as exc:
                    report["errors"].append({"url": url, "error": str(exc)})
                    continue
                validators = {"If-None-Match": response.headers.get("etag"), "If-Modified-Since": response.headers.get("last-modified")}
                _VALIDATORS[url] = {k: v for k, v in validators.items() if v}
                if result["status"] == "unchanged":
                    report["unchanged"] += 1
                else:
                    report["ingested"].append({k: v for k, v in result.items() if not k.startswith("_")} | {"url": url})
    finally:
        if http_client is None:
            await client.aclose()
    return report


async def ingest_forwarded(admin_db, org_id: str, user_id: str, data: bytes, *, court_code: str, now: datetime,
                           list_date: date | None = None, list_type: str | None = None, filename: str | None = None) -> dict:
    """A list a firm member forwarded (an upload from the board; later WhatsApp / e-mail). Stored for
    that firm only. Callers check membership first; a forwarded list never enters any client-intake
    or AI path."""
    result = await ingest_pdf(admin_db, court_code, data, now=now, org_id=org_id, uploaded_by=user_id,
                              filename=filename, list_date=list_date, list_type=list_type)
    await audit_service.alog_action(user_id, org_id, "UPLOAD_CAUSE_LIST", "cause_list", result["cause_list_id"],
                                    metadata={"court_code": court_code, "status": result["status"], "filename": filename,
                                              "items": result.get("items")})
    return result


# ============================================================================ escalation


def recipients_for(level: int, match: dict, roster_partners: list[str]) -> list[str]:
    fallback = match.get("fallback_advocate_id")
    appearing = match.get("appearing_advocate_id")
    if level == 1:
        return [fallback] if fallback else roster_partners
    if level == 2:
        return roster_partners + ([fallback] if fallback else [])
    return roster_partners + [appearing, fallback]


async def escalate(admin_db, now: datetime | None = None) -> dict:
    """Cron (every 15 min, 19:00-22:30 IST, and 07:30): raise the escalation level of unconfirmed
    listings whose clock has run, and notify the fallback, then the partners, then everyone again."""
    now = now or datetime.now(timezone.utc)
    today = ist(now).date()
    days = [today.isoformat(), (today + timedelta(days=1)).isoformat()]
    rows = await _select(admin_db, "listing_matches", "*", list_date__in=days, state__in=["open", "claimed"],
                         list_type__in=list(LISTED_TYPES))
    rows = [r for r in rows if r["match_type"] == "exact" or r["state"] == "claimed"]
    items = {}
    if rows:
        items = {i["id"]: i for i in await _select(admin_db, "cause_list_items", "*", id__in=list({r["item_id"] for r in rows}))}
    partners: dict[str, list[str]] = {}
    notifications, raised = [], 0
    for match in rows:
        item = items.get(match["item_id"])
        if not item or item.get("status") != "listed":
            continue
        level = due_level(match["ingested_at"], _as_date(match["list_date"]), now)
        if level <= (match.get("escalation_level") or 0):
            continue
        org = match["org_id"]
        if org not in partners:
            members = await _select(admin_db, "organization_members", "user_id, role", org_id=org)
            partners[org] = [m["user_id"] for m in members if m["role"] == "partner"] or \
                            [m["user_id"] for m in members if m["role"] == "owner"]
        stamp = now.astimezone(timezone.utc).isoformat()
        await _q(lambda match=match, level=level, stamp=stamp: admin_db.table("listing_matches")
                 .update({"escalation_level": level, "escalated_at": stamp})
                 .eq("id", match["id"]).eq("org_id", match["org_id"]).execute())
        raised += 1
        notifications.append(_payload("listing.escalated", {**match, "escalation_level": level}, item,
                                      recipients_for(level, match, partners[org]), level))
    await _deliver(notifications)
    return {"checked": len(rows), "escalated": raised, "notifications": notifications}


# ============================================================================ board


def _tone(match: dict, item: dict, now: datetime) -> str:
    if match["state"] == "confirmed":
        return "confirmed"
    if item.get("status") != "listed":
        return "deleted"
    if match["list_type"] == "advance":
        return "expected"
    level = max(match.get("escalation_level") or 0, due_level(match["ingested_at"], _as_date(match["list_date"]), now))
    return "red" if level >= 2 else "amber" if level == 1 else "pending"


async def board(db, day: date, now: datetime) -> dict:
    """Tonight's board for the caller's organization (all reads through the caller's RLS client)."""
    matches = await _select(db, "listing_matches", "*", list_date=day.isoformat())
    item_ids = list({m["item_id"] for m in matches})
    items = {i["id"]: i for i in (await _select(db, "cause_list_items", "*", id__in=item_ids) if item_ids else [])}
    case_ids = list({m["court_case_id"] for m in matches if m.get("court_case_id")})
    cases = {c["id"]: c for c in (await _select(db, "court_cases", "*", id__in=case_ids) if case_ids else [])}
    people = {m.get(k) for m in matches for k in ("appearing_advocate_id", "fallback_advocate_id", "confirmed_by") if m.get(k)}
    names = {u["id"]: u.get("full_name") or u.get("email") for u in
             (await _select(db, "users", "id, full_name, email", id__in=list(people)) if people else [])}
    codes = list({i["court_code"] for i in items.values()})
    courts = {c["code"]: c for c in (await _select(db, "courts", "code, name, complex", code__in=codes) if codes else [])}

    def row(match: dict) -> dict:
        item = items.get(match["item_id"], {})
        case = cases.get(match.get("court_case_id")) or {}
        return {
            "id": match["id"], "match_type": match["match_type"], "reason": match["reason"], "state": match["state"],
            "list_type": match["list_type"], "list_date": match["list_date"], "court_code": match["court_code"],
            "court_name": courts.get(match["court_code"], {}).get("name") or match["court_code"],
            "complex": courts.get(match["court_code"], {}).get("complex"),
            "courtroom": item.get("courtroom"), "item_no": item.get("item_no"), "position": item.get("position"),
            "bench": item.get("bench_label"), "segment": item.get("segment"), "status": item.get("status"),
            "case_label": _label(item) if item else None, "parties": item.get("parties"),
            "connected_to": item.get("connected_to"),
            "court_case_id": match.get("court_case_id"), "case_title": case.get("title"),
            "appearing_advocate_id": match.get("appearing_advocate_id"),
            "appearing_advocate": names.get(match.get("appearing_advocate_id")),
            "fallback_advocate_id": match.get("fallback_advocate_id"),
            "fallback_advocate": names.get(match.get("fallback_advocate_id")),
            "confirmed_by": names.get(match.get("confirmed_by")), "confirmed_at": match.get("confirmed_at"),
            "escalation_level": match.get("escalation_level") or 0, "tone": _tone(match, item, now) if item else "pending",
            "hearing_date_set": match.get("hearing_date_set"),
            "warnings": case_warnings(case, ist(now).date()) if case else [],
        }

    listed, possibly, dismissed = [], [], 0
    seen: set[tuple] = set()
    for match in sorted(matches, key=lambda m: m.get("ingested_at") or "", reverse=True):
        item = items.get(match["item_id"], {})
        key = (match.get("court_case_id") or _label(item), match["court_code"], item.get("item_no"), match["list_type"])
        if key in seen:  # the same listing in a fetched and a forwarded copy of the list
            continue
        seen.add(key)
        if match["state"] == "dismissed":
            dismissed += 1
        elif match["match_type"] == "exact" or match["state"] in ("claimed", "confirmed"):
            listed.append(row(match))
        else:
            possibly.append(row(match))

    groups: dict[tuple, list[dict]] = {}
    for entry in listed:
        groups.setdefault((entry["complex"] or entry["court_name"], entry["court_name"], entry["courtroom"] or "Not allotted"), []).append(entry)
    complexes = []
    for (complex_name, court_name, courtroom), entries in sorted(groups.items(), key=lambda g: (g[0][0], g[0][1], _room_order(g[0][2]))):
        entries.sort(key=lambda e: (e["position"] is None, e["position"] or 0, _room_order(e["item_no"] or "")))
        if not complexes or complexes[-1]["complex"] != complex_name:
            complexes.append({"complex": complex_name, "courtrooms": []})
        complexes[-1]["courtrooms"].append({"court_name": court_name, "courtroom": courtroom, "items": entries})
    return {"date": day.isoformat(), "complexes": complexes, "possibly_ours": possibly, "dismissed": dismissed}


def _room_order(value: str):
    numbers = re.findall(r"\d+", value or "")
    return (int(numbers[0]) if numbers else 10 ** 6, value or "")


async def firm_warnings(db, today: date) -> list[dict]:
    """Order-lag and disposed-without-judgment warnings across the matters the caller can see."""
    cases = await _select(db, "court_cases", "id, title, case_number, case_status, last_hearing_date, provider_data")
    out = []
    for case in cases:
        for warning in case_warnings(case, today):
            out.append({"court_case_id": case["id"], "title": case.get("title"), "case_number": case.get("case_number"), **warning})
    return out
