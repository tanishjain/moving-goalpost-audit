"""G3 / W1 — Gate C: registry timing/content validity for the 97 reference cases.

DIAGNOSTIC ONLY. This does NOT repair, re-run, or change the frozen pipeline. It
retrieves ClinicalTrials.gov *version history* for each of the 97 reference-standard
NCT IDs and asks a single mechanical question:

    Is the LATEST registry primary outcome (the one the frozen pipeline compared to
    the publication) substantively concordant with the primary outcome in the LAST
    registry version submitted before enrolment began (the "prospective" version)?

This quantifies Gate C from COORD_G1_estimand_memo.md §5, which is *currently
unverified, not failed by construction*: latest and prospective may coincide.

------------------------------------------------------------------------------------
FROZEN DATE RULE (fixed BEFORE any case was coded; see COORD_G3_work_order.md W1 §2)
------------------------------------------------------------------------------------
1. Study start = `statusModule.startDateStruct.date` from the LATEST registry version.
   - type ACTUAL (or type absent on legacy records) -> actual_start_date
   - type ESTIMATED                                  -> estimated_start_date
   effective_start = actual if available else estimated. If neither exists ->
   gate_c_code = UNASSESSABLE, note NO_VALID_START.
2. Partial dates are padded: 'YYYY' -> YYYY-01-01, 'YYYY-MM' -> YYYY-MM-01. The
   granularity is recorded; month/year-granular starts set needs_human_review=True
   because the prospective/at-start boundary is then ambiguous by up to a month.
3. prospective_version = the version whose posting `date` is the LATEST date on or
   before effective_start. This mirrors OutcomeCheck's "last version before actual
   (else estimated) start" timing rule.
4. If the EARLIEST registry version is already after effective_start (registration at
   or after enrolment) -> gate_c_code = NO_PROSPECTIVE_VERSION.
5. Boundary guard: if the first version *after* the cutoff falls within 31 days of
   effective_start, set needs_human_review=True (date-granularity ambiguity).

------------------------------------------------------------------------------------
CONCORDANCE CODING (mechanical text/structure only — NOT a clinical-equivalence call)
------------------------------------------------------------------------------------
- prospective_primary_outcome and current_latest_primary_outcome are both ' | '-joined
  primaryOutcome measures pulled from the SAME history API with the SAME extractor, so
  the concordance decision is measure-level and apples-to-apples. The concordance
  decision uses current_latest (the registry's latest version). latest_primary_outcome
  is the measure(s) the frozen pipeline actually stored/compared
  (`registered_endpoint_measures`); it is kept for provenance and a separate drift
  check (pipeline-run latest vs current registry latest), NOT for the gate decision,
  because its text formatting differs from the API extractor.
- Normalise each measure (lowercase, strip, collapse whitespace, drop punctuation,
  split on '|' or '<SEP>') and compare as sets:
    * exact set match                    -> CONCORDANT_WITH_PROSPECTIVE
    * differ (both non-empty)            -> DIFFERS_FROM_PROSPECTIVE + needs_human_review
      (a human confirms substantive change vs pure wording — the one place a
      substantive judgment is unavoidable; we flag rather than decide, per the
      work order.)
- prospective version has no structured primaryOutcomes (legacy free-text record)
  -> gate_c_code = UNASSESSABLE, note describes why.

------------------------------------------------------------------------------------
DATA SOURCE NOTE
------------------------------------------------------------------------------------
The public v2 API does NOT expose version history: `GET /api/v2/studies/{nct}/history`
returns 404 (verified 2026-08-17). Version history is served by the internal endpoint
the ClinicalTrials.gov website itself uses:
    https://clinicaltrials.gov/api/int/studies/{nct}/history          (change list)
    https://clinicaltrials.gov/api/int/studies/{nct}/history/{version} (snapshot)
Raw responses are cached under data/raw/ctgov_history/. If this endpoint is later
withdrawn, Gate C for new trials would need an alternative history source; we do NOT
silently fall back to the latest version.

No LLM calls. Deterministic. Cache-first. Run:
    uv run python scripts/validation/retrieve_gate_c_registry_timing.py
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from moving_goalpost.config import RAW_DIR, VALIDATION_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gate_c")

INT_BASE = "https://clinicaltrials.gov/api/int/studies"
HISTORY_CACHE = RAW_DIR / "ctgov_history"
ADJUDICATION_CSV = VALIDATION_DIR / "manual_validation_adjudication.csv"
OUTPUT_CSV = VALIDATION_DIR / "gate_c_registry_timing.csv"
REQUEST_DELAY_S = 0.5
BOUNDARY_DAYS = 31

RETRIEVAL_DATE = "2026-08-17"

CODE_CONCORDANT = "CONCORDANT_WITH_PROSPECTIVE"
CODE_DIFFERS = "DIFFERS_FROM_PROSPECTIVE"
CODE_NO_PROSPECTIVE = "NO_PROSPECTIVE_VERSION"
CODE_UNASSESSABLE = "UNASSESSABLE"


# ---------------------------------------------------------------------------
# HTTP (cache-first, polite, small retry) — self-contained; does not touch the
# frozen pipeline's ctgov client.
# ---------------------------------------------------------------------------


def _get_json(url: str, attempts: int = 3) -> dict:
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                raise requests.exceptions.HTTPError("429 rate limited")
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.RequestException, ValueError) as exc:  # noqa: PERF203
            last_exc = exc
            wait = 2 ** i
            logger.warning("Retry %d for %s after %s (sleep %ds)", i + 1, url, type(exc).__name__, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to GET {url}: {last_exc}")


def fetch_history_list(nct: str) -> list[dict]:
    """Version change-list for a trial (cache-first)."""
    path = HISTORY_CACHE / f"{nct}_history.json"
    if path.exists():
        return json.loads(path.read_text())["changes"]
    logger.info("Fetching history list for %s", nct)
    data = _get_json(f"{INT_BASE}/{nct}/history")
    HISTORY_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    time.sleep(REQUEST_DELAY_S)
    return data["changes"]


def fetch_version(nct: str, version: int) -> dict:
    """A single historical snapshot's protocolSection (cache-first)."""
    path = HISTORY_CACHE / f"{nct}_v{version}.json"
    if path.exists():
        return json.loads(path.read_text())["study"]["protocolSection"]
    logger.info("Fetching %s version %d", nct, version)
    data = _get_json(f"{INT_BASE}/{nct}/history/{version}")
    HISTORY_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    time.sleep(REQUEST_DELAY_S)
    return data["study"]["protocolSection"]


# ---------------------------------------------------------------------------
# Date + text helpers
# ---------------------------------------------------------------------------


def parse_partial_date(s: str | None) -> tuple[date | None, str]:
    """Pad a possibly-partial CT.gov date. Returns (date, granularity)."""
    if not s:
        return None, "none"
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s), "day"
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = map(int, s.split("-"))
        return date(y, m, 1), "month"
    if re.fullmatch(r"\d{4}", s):
        return date(int(s), 1, 1), "year"
    return None, "unparseable"


def normalize_measures(text: str | None) -> set[str]:
    """Normalise a separator-joined measure string into a comparable set.

    Splits on both ' | ' (our history extractor) and ' <SEP> ' (the pipeline's
    `registered_endpoint_measures` column) so either format compares measure-wise.
    """
    if not text or (isinstance(text, float)):
        return set()
    out = set()
    for part in re.split(r"\s*(?:\||<SEP>)\s*", str(text)):
        p = part.lower().strip()
        p = re.sub(r"[^a-z0-9 ]+", " ", p)
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            out.add(p)
    return out


def measures_from_version(protocol: dict) -> list[str]:
    om = protocol.get("outcomesModule") or {}
    primaries = om.get("primaryOutcomes") or []
    return [o.get("measure", "").strip() for o in primaries if o.get("measure", "").strip()]


# ---------------------------------------------------------------------------
# Per-case coding
# ---------------------------------------------------------------------------


def code_case(nct: str, pipeline_latest_measures: str) -> dict:
    row: dict = {
        "nct_id": nct,
        "actual_start_date": "",
        "estimated_start_date": "",
        "effective_start_date": "",
        "start_date_granularity": "",
        "prospective_version_number": "",
        "prospective_version_date": "",
        "latest_version_date": "",
        "prospective_primary_outcome": "",
        "latest_primary_outcome": str(pipeline_latest_measures) if pd.notna(pipeline_latest_measures) else "",
        "current_latest_primary_outcome": "",
        "gate_c_code": "",
        "n_versions": "",
        "changed_after_start": "",
        "notes": "",
        "needs_human_review": False,
        "retrieval_source": "clinicaltrials.gov/api/int history",
    }
    notes: list[str] = []

    try:
        changes = fetch_history_list(nct)
    except Exception as exc:  # noqa: BLE001
        row["gate_c_code"] = CODE_UNASSESSABLE
        row["needs_human_review"] = True
        row["notes"] = f"history retrieval failed: {exc}"
        return row

    row["n_versions"] = len(changes)
    if not changes:
        row["gate_c_code"] = CODE_UNASSESSABLE
        row["needs_human_review"] = True
        row["notes"] = "empty version history"
        return row

    latest_change = changes[-1]
    row["latest_version_date"] = latest_change["date"]

    # Start date from the latest snapshot.
    latest_protocol = fetch_version(nct, latest_change["version"])
    sds = (latest_protocol.get("statusModule") or {}).get("startDateStruct") or {}
    start_raw = sds.get("date")
    start_type = (sds.get("type") or "").upper()
    start_dt, granularity = parse_partial_date(start_raw)
    row["start_date_granularity"] = granularity
    if start_type == "ESTIMATED":
        row["estimated_start_date"] = start_raw or ""
    elif start_raw:
        row["actual_start_date"] = start_raw  # ACTUAL or legacy/untyped
        if not start_type:
            notes.append("start date has no ACTUAL/ESTIMATED type (legacy record)")

    row["current_latest_primary_outcome"] = " | ".join(measures_from_version(latest_protocol))
    # Registry drift check: pipeline value vs current latest.
    if normalize_measures(row["latest_primary_outcome"]) != normalize_measures(row["current_latest_primary_outcome"]):
        notes.append("pipeline latest differs from current registry latest (registry updated since pipeline run)")

    if start_dt is None:
        row["gate_c_code"] = CODE_UNASSESSABLE
        row["needs_human_review"] = True
        notes.append(f"NO_VALID_START (startDateStruct={sds or 'missing'})")
        row["notes"] = "; ".join(notes)
        return row
    row["effective_start_date"] = start_dt.isoformat()
    if granularity in {"month", "year"}:
        row["needs_human_review"] = True
        notes.append(f"start date {granularity}-granular; prospective boundary ambiguous")

    # Pick prospective version: latest posting date <= effective_start.
    dated = [(date.fromisoformat(c["date"]), c) for c in changes]
    on_or_before = [(d, c) for d, c in dated if d <= start_dt]
    after = [(d, c) for d, c in dated if d > start_dt]

    if not on_or_before:
        row["gate_c_code"] = CODE_NO_PROSPECTIVE
        earliest = dated[0][0]
        notes.append(
            f"earliest registry version {earliest.isoformat()} is after start {start_dt.isoformat()} "
            "(registration at/after enrolment)"
        )
        row["changed_after_start"] = ""
        row["notes"] = "; ".join(notes)
        return row

    # Boundary guard: closest post-cutoff version within BOUNDARY_DAYS of start.
    if after:
        nearest_after = min(d for d, _ in after)
        if (nearest_after - start_dt) <= timedelta(days=BOUNDARY_DAYS):
            row["needs_human_review"] = True
            notes.append(f"a version ({nearest_after.isoformat()}) falls within {BOUNDARY_DAYS}d after start")

    prosp_date, prosp_change = on_or_before[-1]
    row["prospective_version_number"] = prosp_change["version"]
    row["prospective_version_date"] = prosp_change["date"]

    prosp_protocol = fetch_version(nct, prosp_change["version"])
    prosp_measures = measures_from_version(prosp_protocol)
    row["prospective_primary_outcome"] = " | ".join(prosp_measures)

    if not prosp_measures:
        row["gate_c_code"] = CODE_UNASSESSABLE
        row["needs_human_review"] = True
        notes.append("prospective version has no structured primaryOutcomes (legacy free-text record)")
        row["notes"] = "; ".join(notes)
        return row

    # Gate decision compares prospective vs the CURRENT latest registry version,
    # both pulled from the same history API with the same extractor (apples-to-apples,
    # measure-level). The pipeline's stored latest (`latest_primary_outcome`) is kept
    # for provenance and a separate drift check (noted above), but is NOT used for the
    # concordance decision because its text formatting differs from the API extractor.
    prosp_set = normalize_measures(row["prospective_primary_outcome"])
    latest_set = normalize_measures(row["current_latest_primary_outcome"])
    if not latest_set:
        row["gate_c_code"] = CODE_UNASSESSABLE
        row["needs_human_review"] = True
        notes.append("current latest version has no structured primaryOutcomes")
    elif prosp_set == latest_set:
        row["gate_c_code"] = CODE_CONCORDANT
        row["changed_after_start"] = False
    else:
        row["gate_c_code"] = CODE_DIFFERS
        row["changed_after_start"] = True
        row["needs_human_review"] = True
        notes.append("prospective vs latest measures differ textually — confirm substantive vs wording")

    row["notes"] = "; ".join(notes)
    return row


HEADER_COMMENT = (
    f"# Gate C registry timing/content validity — 97 reference cases. Retrieval date {RETRIEVAL_DATE}.\n"
    "# DIAGNOSTIC on the FROZEN pipeline; registry-only (no publication judgment).\n"
    "# Frozen date rule: prospective version = last registry version posted on/before effective start\n"
    "#   (actual start else estimated); partial dates padded to first of month/year; boundary <=31d flagged.\n"
    "# Codes: CONCORDANT_WITH_PROSPECTIVE / DIFFERS_FROM_PROSPECTIVE / NO_PROSPECTIVE_VERSION / UNASSESSABLE.\n"
    "# Source: clinicaltrials.gov/api/int history (public v2 /history returns 404). See script docstring.\n"
)


def main() -> None:
    adj = pd.read_csv(ADJUDICATION_CSV)
    ncts = adj[["nct_id", "registered_endpoint_measures"]].drop_duplicates("nct_id")
    logger.info("Coding Gate C for %d reference cases", len(ncts))

    rows = [code_case(r.nct_id, r.registered_endpoint_measures) for r in ncts.itertuples(index=False)]
    out = pd.DataFrame(rows)

    ordered = [
        "nct_id", "actual_start_date", "estimated_start_date", "effective_start_date",
        "start_date_granularity", "prospective_version_number", "prospective_version_date",
        "latest_version_date", "prospective_primary_outcome", "latest_primary_outcome",
        "current_latest_primary_outcome", "gate_c_code", "n_versions", "changed_after_start",
        "needs_human_review", "notes", "retrieval_source",
    ]
    out = out[ordered]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_CSV.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(HEADER_COMMENT)
        out.to_csv(fh, index=False)
    tmp.replace(OUTPUT_CSV)
    logger.info("Wrote %s (%d rows)", OUTPUT_CSV, len(out))

    counts = out["gate_c_code"].value_counts()
    print("\n=== Gate C code counts ===")
    for code, n in counts.items():
        print(f"  {code}: {n}")
    print(f"  needs_human_review: {int(out['needs_human_review'].sum())}")
    flagged = out.loc[out["needs_human_review"], "nct_id"].tolist()
    if flagged:
        print("  flagged NCTs:", ", ".join(flagged))


if __name__ == "__main__":
    main()
