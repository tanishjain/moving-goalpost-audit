"""Public subset of the frozen G5 run harness `scripts/validation/g5_run_ablation.py` (extraction E2).

Each definition below is copied verbatim, in source order, from the signed harness (SHA-256
7f1122682e4b39ccd3c3b73dcc3575f41fb57f74bca7d13847ecc5a74ac3d944). Included: the frozen prompt literals and rendering, the JSON response
schema and response classifier, the deterministic Gate-D collapse, the seed-randomized cell plan and the
strict attempt-journal scan used by `g5_analyze.py`, and the decoding settings per model alias.
Withheld: service transport, authentication and credential handling, run authorization, locking, journal
repair, case loading and run orchestration. This module cannot call any model; the original evaluations
cannot be rerun from this snapshot. See docs/PROVENANCE.md.
"""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

ARMS = (1, 2)

MODELS = {  # requested alias -> (api_type, endpoint, decoding params explicitly set)
    "claude-opus-4.6": ("chat", "/chat/completions", {"temperature": 0.0, "max_tokens": 2048}),
    "gemini-3.1-pro-preview": ("chat", "/chat/completions", {"temperature": 0.0, "max_tokens": 2048}),
    "gpt-5.4": ("responses", "/responses", {"max_output_tokens": 2048}),
}

MAX_ATTEMPTS = 3

ORDER_SEED = 20260818

N_REF = 97

SOURCE_FIELDS = ["nct_id", "trial_title", "registered_endpoint_measures",
                 "registered_endpoint_descriptions", "registered_endpoint_timeframes",
                 "pub_title", "abstract"]

COMMON_PREAMBLE = (
    "You are assessing whether a clinical trial's published report describes the same primary outcome "
    "that was registered for the trial. Use only the supplied case fields. Do not infer facts from "
    "outside the supplied title, abstract, and registry text. Return only the JSON object required by "
    "the response schema, with no additional text."
)

GATE_A_BLOCK = (
    "Step 1 - Publication identity. Decide whether the publication is the trial's PRIMARY-RESULTS "
    "report: the report intended to present the trial's prespecified primary endpoint at its "
    "prespecified analysis or time point. Choose one:\n"
    "- RIGHT_PAPER - this is the primary-results report of this trial.\n"
    "- WRONG_PAPER - this is a secondary/subgroup analysis, a biomarker or ancillary sub-study, a "
    "long-term follow-up or extension that is ancillary to an identifiable earlier primary-results "
    "report, a pooled/meta-analysis, a review, a protocol, or a report of a different trial.\n"
    "- UNASSESSABLE - the supplied publication title and abstract do not contain enough information to decide.\n"
    "A report labelled \"follow-up\" can still be the primary-results report if it is the first mature "
    "report of the prespecified primary endpoint. Choose WRONG_PAPER for a follow-up/extension only when "
    "it is ancillary to an identifiable earlier primary-results report or does not report the prespecified "
    "primary analysis. Do not choose WRONG_PAPER merely because the registered and published outcome "
    "wording differs; endpoint disagreement is assessed in Step 2.\n"
    "If Step 1 is not RIGHT_PAPER, stop: set all Step-2 fields to null and do not perform the outcome "
    "comparison. If Step 1 is RIGHT_PAPER, perform the Gate-D block below."
)

GATE_D_BLOCK = (
    "Primary-outcome equivalence. Compare the latest registered primary outcome or outcomes shown in the "
    "case with the primary outcome or outcomes that the publication abstract explicitly designates. This "
    "is a latest-registry-record-versus-publication comparison; no prospective registry version is "
    "supplied or inferred.\n"
    "First locate what the abstract designates as primary. If the abstract reports outcomes but does not "
    "designate a primary outcome, set endpoint_locatable = false, set the element and structure fields to "
    "null, and set gate_d = UNASSESSABLE; do not infer a primary outcome from salience or order. Otherwise "
    "set endpoint_locatable = true and code every element as SAME, COMPATIBLE, DIFFERENT, UNASSESSABLE, or "
    "NOT_APPLICABLE:\n"
    "- domain - the clinical construct being measured.\n"
    "- measurement - the specific measurement variable or instrument.\n"
    "- metric - the participant-level analysis metric, such as change from baseline, time-to-event, or "
    "proportion responding.\n"
    "- aggregation - the method of aggregation, including any cutoff or composite definition.\n"
    "- timepoint - the assessment time point or window.\n"
    "Use SAME for substantively identical content, COMPATIBLE for non-conflicting expressions of the same "
    "outcome, DIFFERENT for a substantive conflict, UNASSESSABLE when needed information is absent or "
    "ambiguous, and NOT_APPLICABLE only when that element genuinely does not apply. Related outcomes are "
    "not automatically compatible. For example, time-to-progression and progression-free survival differ "
    "if death counts as an event; code the affected element DIFFERENT. Pure wording, abbreviation, or "
    "synonym differences are not material when every applicable element is SAME or COMPATIBLE.\n"
    "Also code:\n"
    "- priority_change: NONE, CHANGED, or UNASSESSABLE.\n"
    "- addition_or_omission: NONE, ADDITION, OMISSION, BOTH, or UNASSESSABLE.\n"
    "- multiplicity_mapping: NONE, ONE_TO_MANY, MANY_TO_ONE, COMPLEX, or UNASSESSABLE.\n"
    "Set gate_d = MATERIAL_CHANGE if at least one element is DIFFERENT, priority is CHANGED, "
    "addition/omission is ADDITION, OMISSION, or BOTH, or multiplicity mapping is ONE_TO_MANY, MANY_TO_ONE, "
    "or COMPLEX. If none of those positive conditions is present but at least one required field is "
    "UNASSESSABLE, set gate_d = UNASSESSABLE. Otherwise set gate_d = NO_MATERIAL_CHANGE. The deterministic "
    "collapse is binding; do not give a gate_d value that contradicts the element and structure fields."
)

SCHEMA_INSTR = {
    1: ("\nReturn ONLY this JSON object (no code fences):\n"
        '{"case_id": <int>, "arm": 1, "gate_a": "RIGHT_PAPER|WRONG_PAPER|UNASSESSABLE", '
        '"endpoint_locatable": <true|false|null>, "elements": {"domain": <code|null>, '
        '"measurement": <code|null>, "metric": <code|null>, "aggregation": <code|null>, '
        '"timepoint": <code|null>}, "priority_change": <code|null>, "addition_or_omission": <code|null>, '
        '"multiplicity_mapping": <code|null>, "gate_d": <"MATERIAL_CHANGE|NO_MATERIAL_CHANGE|UNASSESSABLE"|null>, '
        '"brief_rationale": "<=280 chars"}\n'
        "If gate_a != RIGHT_PAPER set endpoint_locatable, all elements, structure fields, and gate_d to null."),
    2: ("\nReturn ONLY this JSON object (no code fences):\n"
        '{"case_id": <int>, "arm": 2, "gate_a": null, "endpoint_locatable": <true|false>, '
        '"elements": {"domain": <code|null>, "measurement": <code|null>, "metric": <code|null>, '
        '"aggregation": <code|null>, "timepoint": <code|null>}, "priority_change": <code|null>, '
        '"addition_or_omission": <code|null>, "multiplicity_mapping": <code|null>, '
        '"gate_d": "MATERIAL_CHANGE|NO_MATERIAL_CHANGE|UNASSESSABLE", "brief_rationale": "<=280 chars"}'),
}

ELEMENT_KEYS = ["domain", "measurement", "metric", "aggregation", "timepoint"]

RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["case_id", "arm", "gate_a", "endpoint_locatable", "elements",
                 "priority_change", "addition_or_omission", "multiplicity_mapping",
                 "gate_d", "brief_rationale"],
    "properties": {
        "case_id": {"type": "integer", "minimum": 1},
        "arm": {"type": "integer", "enum": [1, 2]},
        "gate_a": {"enum": ["RIGHT_PAPER", "WRONG_PAPER", "UNASSESSABLE", None]},
        "endpoint_locatable": {"type": ["boolean", "null"]},
        "elements": {
            "type": "object", "additionalProperties": False,
            "required": ELEMENT_KEYS,
            "properties": {k: {"enum": ["SAME", "COMPATIBLE", "DIFFERENT", "UNASSESSABLE",
                                        "NOT_APPLICABLE", None]} for k in ELEMENT_KEYS},
        },
        "priority_change": {"enum": ["NONE", "CHANGED", "UNASSESSABLE", None]},
        "addition_or_omission": {"enum": ["NONE", "ADDITION", "OMISSION", "BOTH", "UNASSESSABLE", None]},
        "multiplicity_mapping": {"enum": ["NONE", "ONE_TO_MANY", "MANY_TO_ONE", "COMPLEX", "UNASSESSABLE", None]},
        "gate_d": {"enum": ["MATERIAL_CHANGE", "NO_MATERIAL_CHANGE", "UNASSESSABLE", None]},
        "brief_rationale": {"type": "string", "maxLength": 280},
    },
}

_VALIDATOR = Draft202012Validator(RESPONSE_SCHEMA)

NOT_REPORTED = "[NOT REPORTED]"

def _field(v) -> str:
    """Render a case field; missing/NaN/empty -> explicit [NOT REPORTED] (never literal 'nan')."""
    if v is None:
        return NOT_REPORTED
    if isinstance(v, float) and np.isnan(v):
        return NOT_REPORTED
    s = str(v).strip()
    return NOT_REPORTED if s == "" or s.lower() == "nan" else s

def case_block(case_id: int, arm: int, r: dict) -> str:
    return (
        f"\n--- CASE (case_id={case_id}, arm={arm}) ---\n"
        f"nct_id: {_field(r['nct_id'])}\n"
        f"trial_title: {_field(r['trial_title'])}\n"
        f"registered_primary_outcome_measure: {_field(r['registered_endpoint_measures'])}\n"
        f"registered_primary_outcome_description: {_field(r['registered_endpoint_descriptions'])}\n"
        f"registered_primary_outcome_timeframe: {_field(r['registered_endpoint_timeframes'])}\n"
        f"publication_title: {_field(r['pub_title'])}\n"
        f"publication_abstract: {_field(r['abstract'])}\n"
    )

def render_prompt(arm: int, case_id: int, r: dict) -> str:
    if arm == 1:
        return COMMON_PREAMBLE + "\n\n" + GATE_A_BLOCK + "\n\n" + GATE_D_BLOCK + "\n" + \
            case_block(case_id, 1, r) + SCHEMA_INSTR[1]
    if arm == 2:
        return COMMON_PREAMBLE + "\n\n" + GATE_D_BLOCK + "\n" + \
            case_block(case_id, 2, r) + SCHEMA_INSTR[2]
    raise ValueError(f"arm {arm} not in this two-arm study")

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def gate_d_collapse(el: dict, prio, addom, mult) -> str:
    if any(el.get(k) == "DIFFERENT" for k in ELEMENT_KEYS) or prio == "CHANGED" \
            or addom in {"ADDITION", "OMISSION", "BOTH"} \
            or mult in {"ONE_TO_MANY", "MANY_TO_ONE", "COMPLEX"}:
        return "MATERIAL_CHANGE"
    if any(v == "UNASSESSABLE" for v in list(el.values()) + [prio, addom, mult]):
        return "UNASSESSABLE"
    return "NO_MATERIAL_CHANGE"

def classify_response(arm: int, case_id: int, text: str) -> tuple[str, str, dict | None]:
    """Return (status, detail, parsed). status in OK/PARSE_FAIL/SCHEMA_FAIL/SEMANTIC_FAIL.
    NEVER returns a transport status — transport is handled before parsing."""
    t = text.strip()
    if t.startswith("```"):
        t = "\n".join(l for l in t.splitlines() if not l.strip().startswith("```")).strip()
    try:
        obj = json.loads(t)
    except Exception as e:  # noqa: BLE001
        return "PARSE_FAIL", f"json: {str(e)[:150]}", None
    errs = sorted(_VALIDATOR.iter_errors(obj), key=lambda e: e.path)
    if errs:
        return "SCHEMA_FAIL", "; ".join(e.message for e in errs[:3])[:200], obj
    # echo checks
    if obj["case_id"] != case_id:
        return "SCHEMA_FAIL", f"case_id echo {obj['case_id']} != {case_id}", obj
    if obj["arm"] != arm:
        return "SCHEMA_FAIL", f"arm echo {obj['arm']} != {arm}", obj
    # semantic (null-population + deterministic collapse)
    el = obj["elements"]
    if arm == 2:
        if obj["gate_a"] is not None:
            return "SEMANTIC_FAIL", "arm2 gate_a must be null", obj
    else:  # arm 1
        if obj["gate_a"] is None:
            return "SEMANTIC_FAIL", "arm1 gate_a must not be null", obj
        if obj["gate_a"] != "RIGHT_PAPER":
            if obj["endpoint_locatable"] is not None or obj["gate_d"] is not None \
                    or any(el[k] is not None for k in ELEMENT_KEYS) \
                    or obj["priority_change"] is not None or obj["addition_or_omission"] is not None \
                    or obj["multiplicity_mapping"] is not None:
                return "SEMANTIC_FAIL", "gate_a!=RIGHT_PAPER but step-2 fields not all null", obj
            return "OK", "", obj
    # step 2 performed (arm2, or arm1 RIGHT_PAPER)
    loc = obj["endpoint_locatable"]
    if loc is None:
        return "SEMANTIC_FAIL", "endpoint_locatable must be set when step 2 is performed", obj
    if loc is False:
        if any(el[k] is not None for k in ELEMENT_KEYS) \
                or obj["priority_change"] is not None or obj["addition_or_omission"] is not None \
                or obj["multiplicity_mapping"] is not None or obj["gate_d"] != "UNASSESSABLE":
            return ("SEMANTIC_FAIL",
                    "endpoint_locatable false requires null elements AND null structure fields "
                    "(priority/addition_or_omission/multiplicity) AND gate_d=UNASSESSABLE", obj)
        return "OK", "", obj
    for k in ELEMENT_KEYS:
        if el[k] is None:
            return "SEMANTIC_FAIL", f"element {k} null with endpoint_locatable true", obj
    for f in ["priority_change", "addition_or_omission", "multiplicity_mapping", "gate_d"]:
        if obj[f] is None:
            return "SEMANTIC_FAIL", f"{f} null with endpoint_locatable true", obj
    expected = gate_d_collapse(el, obj["priority_change"], obj["addition_or_omission"],
                               obj["multiplicity_mapping"])
    if obj["gate_d"] != expected:
        return "SEMANTIC_FAIL", f"gate_d {obj['gate_d']} contradicts deterministic {expected}", obj
    return "OK", "", obj

def ordered_plan(cases: pd.DataFrame) -> list[tuple[int, int, str]]:
    """Deterministic, seed-randomized (case_id, arm, model) cell plan."""
    plan = [(int(c.case_id), a, m) for c in cases.itertuples() for a in ARMS for m in MODELS]
    order = np.random.RandomState(ORDER_SEED).permutation(len(plan))
    return [plan[i] for i in order]

class JournalIntegrityError(Exception):
    """Journal corruption / contract violation — hard stop, never last-write-wins."""

def read_journal(attempts_path: Path) -> list[dict]:
    """Read all attempt records. The physical torn tail must already have been repaired
    (repair_journal); here EVERY non-empty line must be valid JSON — a corrupt line (final or not) is a
    hard integrity error."""
    if not attempts_path.exists():
        return []
    recs = []
    for i, ln in enumerate(attempts_path.read_text().splitlines()):
        if not ln.strip():
            continue
        try:
            recs.append(json.loads(ln))
        except json.JSONDecodeError as e:
            raise JournalIntegrityError(f"corrupt journal line {i}: {e}")
    return recs

def scan_journal(attempts_path: Path, valid_keys: set | None = None) -> tuple[dict, dict]:
    """AUTHORITATIVE journal scan with self-validation (P0-H item 2). Returns
    (terminal_keys, resume_next). Validates, per key: known key (if valid_keys given); contiguous
    attempt numbers 1..k; at most one terminal and it is last; only TRANSPORT_RETRY may be
    nonterminal; a key at MAX_ATTEMPTS cannot remain nonterminal; stable prompt hash."""
    per_key: dict[tuple, list[dict]] = {}
    for r in read_journal(attempts_path):
        per_key.setdefault((int(r["case_id"]), int(r["arm"]), r["model"]), []).append(r)
    terminal_keys, resume_next = {}, {}
    for key, atts in per_key.items():
        if valid_keys is not None and key not in valid_keys:
            raise JournalIntegrityError(f"journal has unknown key {key} not in the frozen plan")
        atts = sorted(atts, key=lambda a: int(a["attempt"]))
        nums = [int(a["attempt"]) for a in atts]
        if nums != list(range(1, len(nums) + 1)):
            raise JournalIntegrityError(f"{key}: attempt numbers not contiguous from 1: {nums}")
        if len({a["prompt_sha256"] for a in atts}) != 1:
            raise JournalIntegrityError(f"{key}: prompt hash not stable across attempts")
        terminals = [a for a in atts if a.get("terminal")]
        if len(terminals) > 1:
            raise JournalIntegrityError(f"{key}: {len(terminals)} terminal attempts")
        if terminals and atts[-1] is not terminals[0]:
            raise JournalIntegrityError(f"{key}: attempts recorded after a terminal record")
        for a in atts:
            if not a.get("terminal") and a.get("status") != "TRANSPORT_RETRY":
                raise JournalIntegrityError(f"{key}: nonterminal attempt with status {a.get('status')}")
        if terminals:
            terminal_keys[key] = terminals[0]
        else:
            if nums[-1] >= MAX_ATTEMPTS:
                raise JournalIntegrityError(f"{key}: reached MAX_ATTEMPTS with no terminal record")
            resume_next[key] = nums[-1] + 1
    return terminal_keys, resume_next
