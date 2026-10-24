"""Indian practice workflows: guided matter packs with deadlines computed in code.

Each pack takes the matter's key dates and facts and returns, without any model involved:

  deadlines   statutory time limits computed from the dates given, each with its basis
  flags       problems found (a deadline already missed, a cheque presented too late...)
  checklist   documents and steps the matter needs
  draft       what to draft next, prefilled for the drafting engine (the only AI step)

Deadlines follow the statute's wording (e.g. "within thirty days of the receipt of information
from the bank"); court practice on computing them (the day of the event excluded, as under s. 9
of the General Clauses Act, 1897) is applied, but every date should still be checked by the
lawyer, and courts may condone delay where the statute allows it.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

CRIMINAL_CODES_START = date(2024, 7, 1)  # BNS / BNSS / BSA in force


class WorkflowError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str = "text"  # text | date | amount | number | boolean | choice
    required: bool = False
    help: str | None = None
    choices: tuple[str, ...] = ()


@dataclass
class Result:
    deadlines: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    draft: dict | None = None
    summary: str = ""

    def deadline(self, label: str, when: date, basis: str, today: date, *, done: bool = False) -> date:
        if done:
            status = "done"
        elif when < today:
            status = "missed"
        elif (when - today).days <= 7:
            status = "due_soon"
        else:
            status = "upcoming"
        self.deadlines.append({"label": label, "date": when.isoformat(), "days_left": (when - today).days, "status": status, "basis": basis})
        return when

    def flag(self, severity: str, message: str) -> None:
        self.flags.append({"severity": severity, "message": message})


@dataclass(frozen=True)
class Pack:
    id: str
    name: str
    area: str
    description: str
    fields: tuple[Field, ...]
    compute: Callable[[dict, date], Result]

    def describe(self) -> dict:
        return {
            "id": self.id, "name": self.name, "area": self.area, "description": self.description,
            "fields": [{k: v for k, v in f.__dict__.items() if v not in (None, ())} for f in self.fields],
        }


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _date(inputs: dict, key: str) -> date | None:
    value = inputs.get(key)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise WorkflowError(f"{key} must be a date (YYYY-MM-DD)") from None


def _amount(inputs: dict, key: str) -> float | None:
    value = inputs.get(key)
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("₹", "").strip())
    except ValueError:
        raise WorkflowError(f"{key} must be a number") from None


def _rupees(amount: float | None) -> str:
    if amount is None:
        return "[amount]"
    whole = f"{amount:,.0f}"
    # Indian grouping: 12,34,567
    digits = str(int(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        head = ",".join([head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1])
        whole = f"{head},{tail}"
    return f"Rs. {whole}"


# ----------------------------------------------------------------------------- cheque dishonour (s. 138 NI Act)


def _cheque_bounce(inputs: dict, today: date) -> Result:
    r = Result()
    cheque_date = _date(inputs, "cheque_date")
    presented = _date(inputs, "presented_on")
    memo = _date(inputs, "return_memo_received_on")
    notice_sent = _date(inputs, "notice_sent_on")
    notice_received = _date(inputs, "notice_received_on")
    amount = _amount(inputs, "amount")
    if memo is None:
        raise WorkflowError("The date the bank's return memo was received is needed")

    if cheque_date and presented:
        valid_until = add_months(cheque_date, 3)
        if presented > valid_until:
            r.flag("high", f"The cheque was presented on {presented:%d %b %Y}, after its 3-month validity ended on "
                           f"{valid_until:%d %b %Y}: s. 138 (proviso (a)) may not apply.")

    notice_by = r.deadline("Send the demand notice", memo + timedelta(days=30),
                           "s. 138 proviso (b) NI Act: within 30 days of receiving the bank's information", today,
                           done=bool(notice_sent))
    if notice_sent and notice_sent > notice_by:
        r.flag("high", f"The notice was sent on {notice_sent:%d %b %Y}, after the 30-day limit ({notice_by:%d %b %Y}): "
                       "the complaint may not be maintainable on this dishonour.")

    if notice_received:
        pay_by = r.deadline("Drawer's time to pay ends", notice_received + timedelta(days=15),
                            "s. 138 proviso (c) NI Act: 15 days from receipt of the notice", today)
        cause = pay_by + timedelta(days=1)
        complaint_by = r.deadline("File the complaint", add_months(cause, 1) - timedelta(days=1),
                                  "s. 142(1)(b) NI Act: within one month of the cause of action (the day after the 15 days end)", today)
        if today < cause:
            r.next_steps.append(f"Wait until {cause:%d %b %Y}: a complaint filed before the 15 days end is premature.")
        elif today > complaint_by:
            r.flag("high", "The one-month limit for the complaint has passed: file with an application to condone the delay "
                           "(s. 142(1)(b) proviso), showing sufficient cause.")
        else:
            r.next_steps.append(f"File the complaint between {cause:%d %b %Y} and {complaint_by:%d %b %Y}.")
    elif notice_sent:
        r.next_steps.append("Record when the drawer received the notice (postal tracking / acknowledgement card): "
                            "the 15 days run from receipt.")
    else:
        r.next_steps.append(f"Send the demand notice by {notice_by:%d %b %Y} by registered post / speed post and keep the tracking proof.")

    r.next_steps += [
        "File where the payee's bank branch (where the cheque was presented for collection) is located: s. 142(2)(a) NI Act.",
        "Consider seeking interim compensation of up to 20% of the cheque amount: s. 143A NI Act.",
    ]
    r.checklist = [
        "Original dishonoured cheque",
        "Bank return memo with the reason for dishonour",
        "Copy of the demand notice, postal receipt and tracking / acknowledgement",
        "Proof of the debt or liability (loan agreement, invoices, ledger, messages)",
        "Affidavit of evidence of the complainant",
        "Authority letter / board resolution if the payee is a company",
    ]
    r.summary = (f"Cheque dishonour for {_rupees(amount)}: notice due by {notice_by:%d %b %Y}"
                 + (f", complaint window ends {r.deadlines[-1]['date']}" if notice_received else "") + ".")
    if not notice_sent:
        r.draft = {
            "doc_type": "legal_notice",
            "facts": (f"Cheque for {_rupees(amount)} dated {cheque_date:%d %B %Y} " if cheque_date else f"Cheque for {_rupees(amount)} ")
                     + f"was dishonoured; the bank's return memo was received on {memo:%d %B %Y}."
                     + (f" Drawer: {inputs['drawer_name']}." if inputs.get("drawer_name") else "")
                     + (f" Reason for return: {inputs['return_reason']}." if inputs.get("return_reason") else ""),
            "instructions": "Statutory demand notice under Section 138 of the Negotiable Instruments Act, 1881: demand payment "
                            "of the cheque amount within 15 days of receipt, failing which a complaint will be filed under "
                            "Sections 138 and 142.",
        }
    return r


# ----------------------------------------------------------------------------- consumer complaint (CPA 2019)


def _consumer(inputs: dict, today: date) -> Result:
    r = Result()
    cause = _date(inputs, "cause_of_action_on")
    paid = _amount(inputs, "amount_paid")
    if cause is None:
        raise WorkflowError("The date the cause of action arose (e.g. when the defect or deficiency appeared) is needed")
    limit = r.deadline("File the consumer complaint", add_months(cause, 24) - timedelta(days=1),
                       "s. 69(1) Consumer Protection Act, 2019: within two years of the cause of action", today)
    if today > limit:
        r.flag("high", "The two-year limitation has passed: file with an application to condone the delay showing sufficient cause (s. 69(2)).")
    if paid is not None:
        if paid <= 50_00_000:
            forum = "District Consumer Disputes Redressal Commission (consideration paid up to Rs. 50 lakh)"
        elif paid <= 2_00_00_000:
            forum = "State Consumer Disputes Redressal Commission (consideration paid above Rs. 50 lakh, up to Rs. 2 crore)"
        else:
            forum = "National Consumer Disputes Redressal Commission (consideration paid above Rs. 2 crore)"
        r.next_steps.append(f"Forum: {forum}, under the Consumer Protection (Jurisdiction) Rules, 2021. Check for later revisions.")
        if paid <= 5_00_000:
            r.next_steps.append("No court fee for complaints where the consideration paid is up to Rs. 5 lakh.")
    r.next_steps += [
        "File online on the e-Daakhil portal (edaakhil.nic.in), or in person.",
        "The complaint can be filed where the complainant lives or works: s. 34(2)(d) / s. 47 CPA 2019.",
        "Send a legal notice to the seller / service provider first: it is not mandatory, but shows the attempt to resolve.",
    ]
    r.checklist = [
        "Invoice / bill and proof of payment",
        "Warranty card, terms of sale or service",
        "Photos, job cards or expert report showing the defect or deficiency",
        "Correspondence and complaint numbers with the seller / service centre",
        "Copy of any legal notice and the reply",
        "Identity and address proof of the complainant",
    ]
    r.summary = f"Consumer complaint: file by {limit:%d %b %Y}" + (f" for consideration of {_rupees(paid)}." if paid is not None else ".")
    r.draft = {
        "doc_type": "legal_notice",
        "facts": f"Consumer dispute. Amount paid: {_rupees(paid)}. Cause of action arose on {cause:%d %B %Y}."
                 + (f" Opposite party: {inputs['opposite_party']}." if inputs.get("opposite_party") else "")
                 + (f" Problem: {inputs['grievance']}." if inputs.get("grievance") else ""),
        "instructions": "Pre-complaint legal notice under the Consumer Protection Act, 2019, seeking replacement or refund "
                        "and compensation within 15 days, failing which a complaint will be filed before the appropriate Commission.",
    }
    return r


# ----------------------------------------------------------------------------- bail (BNSS / CrPC)


def _bail(inputs: dict, today: date) -> Result:
    r = Result()
    offence_on = _date(inputs, "offence_date")
    custody_from = _date(inputs, "custody_since")
    max_years = _amount(inputs, "max_punishment_years")
    life_or_death = str(inputs.get("punishable_with_death_or_life", "")).lower() in ("true", "yes", "1")
    first_offender = str(inputs.get("first_time_offender", "")).lower() in ("true", "yes", "1")
    chargesheet_filed = str(inputs.get("chargesheet_filed", "")).lower() in ("true", "yes", "1")
    if offence_on is None:
        raise WorkflowError("The date of the alleged offence is needed (it decides BNSS or CrPC)")

    new = offence_on >= CRIMINAL_CODES_START
    code = "BNSS" if new else "CrPC"
    regular, sessions, anticipatory, default, undertrial = (
        ("s. 480 BNSS", "s. 483 BNSS", "s. 482 BNSS", "s. 187(3) BNSS", "s. 479 BNSS") if new
        else ("s. 437 CrPC", "s. 439 CrPC", "s. 438 CrPC", "s. 167(2) CrPC", "s. 436A CrPC")
    )
    r.next_steps.append(
        f"The offence is dated {offence_on:%d %b %Y}, {'on or after' if new else 'before'} 1 July 2024: "
        f"procedure under the {code}" + ("" if new else " (proceedings begun before 1 July 2024 continue under it)") + "."
    )
    if custody_from is None:
        r.next_steps.append(f"Not in custody: anticipatory bail under {anticipatory} (Sessions Court or High Court).")
        r.draft = {
            "doc_type": "bail_application",
            "facts": f"Apprehension of arrest. Alleged offence on {offence_on:%d %B %Y}."
                     + (f" Sections alleged: {inputs['sections']}." if inputs.get("sections") else ""),
            "instructions": f"Application for anticipatory bail under {anticipatory}.",
        }
    else:
        serious = life_or_death or (max_years is not None and max_years >= 10)
        days = 90 if serious else 60
        reason = "punishable with death, life imprisonment or imprisonment of 10 years or more" if serious else "other offences"
        default_on = r.deadline(
            "Default bail if no chargesheet", custody_from + timedelta(days=days),
            f"{default}: investigation must be completed within {days} days ({reason})", today, done=chargesheet_filed,
        )
        if not chargesheet_filed and today >= default_on:
            r.flag("high", f"{days} days in custody have passed: if no chargesheet has been filed, apply for default bail "
                           f"under {default} now (the right is lost once the chargesheet is filed).")
        if max_years and not life_or_death:
            share = 1 / 3 if (new and first_offender) else 1 / 2
            undertrial_on = custody_from + timedelta(days=round(max_years * 365.25 * share))
            r.deadline(
                "Release as an undertrial", undertrial_on,
                f"{undertrial}: detention up to {'one-third' if share < 0.5 else 'one-half'} of the maximum sentence"
                + (" (first-time offender)" if share < 0.5 else ""), today,
            )
        r.next_steps.append(f"Regular bail: {regular} (Magistrate) or {sessions} (Sessions Court / High Court).")
        r.draft = {
            "doc_type": "bail_application",
            "facts": f"In custody since {custody_from:%d %B %Y}. Alleged offence on {offence_on:%d %B %Y}."
                     + (f" Sections alleged: {inputs['sections']}." if inputs.get("sections") else "")
                     + (" First-time offender." if first_offender else "")
                     + (" Chargesheet filed." if chargesheet_filed else " Chargesheet not yet filed."),
            "instructions": f"Application for regular bail under {sessions if serious else regular}.",
        }
    r.checklist = [
        "Copy of the FIR and the sections alleged",
        "Arrest memo and remand orders",
        "Chargesheet (if filed) or the date it was due",
        "Surety details and identity / address proof",
        "Previous bail orders, if any, and criminal antecedents",
        "Medical or family circumstances supporting bail",
    ]
    r.summary = f"Bail under the {code}" + (f"; default bail date {r.deadlines[0]['date']}." if r.deadlines else ".")
    return r


PACKS: dict[str, Pack] = {
    p.id: p
    for p in (
        Pack(
            "cheque_bounce", "Cheque bounce (Section 138 NI Act)", "Criminal / commercial",
            "Notice, payment and complaint deadlines from the dishonour dates; the demand notice drafted.",
            (
                Field("drawer_name", "Drawer (who issued the cheque)"),
                Field("amount", "Cheque amount (Rs.)", "amount", True),
                Field("cheque_date", "Date on the cheque", "date"),
                Field("presented_on", "Date presented to the bank", "date"),
                Field("return_memo_received_on", "Date the bank's return memo was received", "date", True),
                Field("return_reason", "Reason on the memo", help="e.g. Funds insufficient"),
                Field("notice_sent_on", "Demand notice sent on", "date", help="Leave empty if not sent yet"),
                Field("notice_received_on", "Notice received by the drawer on", "date", help="From postal tracking"),
            ),
            _cheque_bounce,
        ),
        Pack(
            "consumer_complaint", "Consumer complaint (CPA 2019)", "Consumer",
            "Limitation, the right Commission by amount paid, filing checklist and a pre-complaint notice.",
            (
                Field("opposite_party", "Seller / service provider"),
                Field("grievance", "What went wrong"),
                Field("amount_paid", "Amount paid (Rs.)", "amount", True),
                Field("cause_of_action_on", "Date the problem arose", "date", True),
            ),
            _consumer,
        ),
        Pack(
            "bail", "Bail (BNSS / CrPC)", "Criminal",
            "Which code applies, default-bail and undertrial-release dates, and the right bail application.",
            (
                Field("sections", "Sections alleged", help="e.g. 318(4) BNS"),
                Field("offence_date", "Date of the alleged offence", "date", True),
                Field("custody_since", "In custody since", "date", help="Leave empty for anticipatory bail"),
                Field("max_punishment_years", "Maximum punishment (years)", "number"),
                Field("punishable_with_death_or_life", "Punishable with death or life imprisonment", "boolean"),
                Field("first_time_offender", "First-time offender", "boolean"),
                Field("chargesheet_filed", "Chargesheet filed", "boolean"),
            ),
            _bail,
        ),
    )
}


def evaluate(pack_id: str, inputs: dict, today: date | None = None) -> dict:
    pack = PACKS.get(pack_id)
    if pack is None:
        raise WorkflowError(f"Unknown workflow {pack_id!r}")
    missing = [f.label for f in pack.fields if f.required and inputs.get(f.key) in (None, "")]
    if missing:
        raise WorkflowError("Required: " + ", ".join(missing))
    result = pack.compute(inputs, today or date.today())
    result.deadlines.sort(key=lambda d: d["date"])
    return {"workflow": pack.id, "name": pack.name, **result.__dict__}
