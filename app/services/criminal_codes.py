"""Which criminal codes govern a matter: the one place that decides IPC/BNS and CrPC/BNSS.

The three 2023 codes (BNS, BNSS, BSA) came into force on 1 July 2024. Two different dates decide
which law applies, and they must not be confused:

  substantive code   IPC or BNS, by the date of the offence. Punishment is fixed by the law in
                     force when the offence was committed (Article 20(1) of the Constitution), so
                     an offence before 1 July 2024 is punished under the IPC even if the FIR,
                     arrest or trial comes later. Used for the punishment lookup.

  procedural code    CrPC or BNSS, by when the proceeding began. Section 531(2)(a) BNSS saves
                     appeals, applications, trials, inquiries and investigations pending
                     immediately before 1 July 2024: they continue under the CrPC. So the
                     investigation start (FIR registered; for a complaint case, the complaint
                     filed) decides, not the offence date. Used for default bail
                     (s. 167(2) CrPC / s. 187(3) BNSS) and the bail provisions.

One field set is shared by every feature (custody watch, bail pack, research): `offence_date`,
`fir_date` and `investigation_started_on` (defaults to `fir_date`; P22's "proceeding instituted
on" is the same date and should be passed here as `investigation_started_on`), with
`arrest_date` as a flagged fallback.

Flags are raised, never resolved, where the law is unsettled:

  fir_date_missing      no FIR / investigation date: the provision is assumed from the arrest date
                        (or, with no arrest either, the offence date)
  transition_s531       offence before 1 July 2024, investigation on or after: the BNSS procedure
                        applies under s. 531 BNSS, but High Courts differ on edge cases; the
                        lawyer checks
  code_mismatch         `check_sections` found BNS sections for a pre-July offence or IPC sections
                        for a later one

Usage:

    codes = criminal_codes(offence_date=date(2024, 6, 20), fir_date=date(2024, 7, 5))
    codes.substantive          # "IPC"
    codes.procedural           # "BNSS"
    codes.provision("default_bail")   # "s. 187(3) BNSS"
    codes.flags                # ({"code": "transition_s531", ...},)
"""

from dataclasses import dataclass, field
from datetime import date

CODES_START = date(2024, 7, 1)  # BNS / BNSS / BSA in force

TRANSITION_MESSAGE = "Offence before 1 Jul 2024, FIR after: check s. 531 BNSS"

# provision key -> (CrPC, BNSS)
PROVISIONS: dict[str, tuple[str, str]] = {
    "default_bail": ("s. 167(2) CrPC", "s. 187(3) BNSS"),
    "regular_bail": ("s. 437 CrPC", "s. 480 BNSS"),
    "sessions_bail": ("s. 439 CrPC", "s. 483 BNSS"),
    "anticipatory_bail": ("s. 438 CrPC", "s. 482 BNSS"),
    "undertrial_release": ("s. 436A CrPC", "s. 479 BNSS"),
}


@dataclass(frozen=True)
class CriminalCodes:
    substantive: str | None  # "IPC" | "BNS"; None when the offence date isn't known
    procedural: str  # "CrPC" | "BNSS"
    procedure_date: date | None  # the date that decided the procedural code
    procedure_from: str  # "investigation_started_on" | "fir_date" | "arrest_date" | "offence_date" | "today"
    flags: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def new_procedure(self) -> bool:
        return self.procedural == "BNSS"

    def provision(self, key: str) -> str:
        """The section for `key` (see PROVISIONS) under the procedural code."""
        old, new = PROVISIONS[key]
        return new if self.new_procedure else old

    def flag_codes(self) -> set[str]:
        return {f["code"] for f in self.flags}

    def explain(self) -> str:
        """One line for the lawyer: which codes and why."""
        parts = []
        if self.substantive:
            parts.append(f"Punishment under the {self.substantive} (offence {'on or after' if self.substantive == 'BNS' else 'before'} 1 July 2024)")
        label = {"investigation_started_on": "investigation began", "fir_date": "FIR registered", "arrest_date": "arrest (FIR date not entered)",
                 "offence_date": "offence date (no FIR or arrest date)", "today": "today (no dates entered)"}[self.procedure_from]
        when = f" {self.procedure_date:%d %b %Y}" if self.procedure_date else ""
        parts.append(f"procedure under the {self.procedural} ({label}{when}; s. 531 BNSS)")
        return "; ".join(parts) + "."

    def as_dict(self) -> dict:
        return {"substantive": self.substantive, "procedural": self.procedural,
                "procedure_date": self.procedure_date.isoformat() if self.procedure_date else None,
                "procedure_from": self.procedure_from, "flags": list(self.flags), "explanation": self.explain()}


def criminal_codes(
    offence_date: date | None,
    *,
    fir_date: date | None = None,
    investigation_started_on: date | None = None,
    arrest_date: date | None = None,
    today: date | None = None,
) -> CriminalCodes:
    """Decide the substantive code (by offence date) and the procedural code (by when the
    investigation began, s. 531 BNSS), with the transition flags. Pure: no I/O."""
    substantive = None if offence_date is None else ("BNS" if offence_date >= CODES_START else "IPC")
    flags: list[dict] = []

    started, source = investigation_started_on, "investigation_started_on"
    if started is None and fir_date is not None:
        started, source = fir_date, "fir_date"
    if started is None:
        if arrest_date is not None:
            started, source = arrest_date, "arrest_date"
            flags.append({"code": "fir_date_missing", "severity": "medium",
                          "message": "FIR date not entered: provision assumed from arrest date"})
        elif offence_date is not None:
            started, source = offence_date, "offence_date"
            flags.append({"code": "fir_date_missing", "severity": "medium",
                          "message": "FIR date not entered: provision assumed from the offence date"})
        else:
            started, source = today, "today"
            flags.append({"code": "fir_date_missing", "severity": "medium",
                          "message": "No offence, FIR or arrest date: provision assumed from today"})

    procedural = "BNSS" if started is None or started >= CODES_START else "CrPC"
    if offence_date is not None and offence_date < CODES_START and procedural == "BNSS":
        flags.append({"code": "transition_s531", "severity": "medium", "message": TRANSITION_MESSAGE})
    return CriminalCodes(substantive, procedural, started, source, tuple(flags))


def check_sections(codes: CriminalCodes, section_codes: list[str]) -> list[dict]:
    """Flags for sections cited under the wrong substantive code (e.g. BNS for a 2023 offence)."""
    if codes.substantive is None:
        return []
    wrong = sorted({c for c in section_codes if c in ("IPC", "BNS") and c != codes.substantive})
    if not wrong:
        return []
    return [{"code": "code_mismatch", "severity": "high",
             "message": f"{'/'.join(wrong)} sections entered, but an offence dated "
                        f"{'on or after' if codes.substantive == 'BNS' else 'before'} 1 July 2024 is punished under the "
                        f"{codes.substantive}: check the sections."}]
