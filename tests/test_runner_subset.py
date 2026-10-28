"""The exported public subset of the frozen run harness: templates, response classifier, journal scan, plan order."""
import json

import pandas as pd
import pytest

import g5_run_ablation as runner
from conftest import ROOT

PLACEHOLDER = {f: "{" + f + "}" for f in runner.SOURCE_FIELDS}


@pytest.mark.parametrize("arm", [1, 2])
def test_shipped_templates_are_the_frozen_rendering_with_placeholders(arm):
    shipped = (ROOT / f"code/prompts/g5/arm{arm}_prompt_template.txt").read_text()
    body = shipped.split("\n", 2)[2]                       # drop the two-line provenance header
    assert body == runner.render_prompt(arm, "{case_id}", PLACEHOLDER) + "\n"
    assert "publication_abstract: {abstract}" in body
    assert json.loads((ROOT / "code/prompts/g5/response_schema.json").read_text()) == runner.RESPONSE_SCHEMA


def _resp(**over):
    base = {"case_id": 7, "arm": 2, "gate_a": None, "endpoint_locatable": True,
            "elements": {k: "SAME" for k in runner.ELEMENT_KEYS}, "priority_change": "NONE",
            "addition_or_omission": "NONE", "multiplicity_mapping": "NONE", "gate_d": "NO_MATERIAL_CHANGE",
            "brief_rationale": "x"}
    base.update(over)
    return json.dumps(base)


def test_response_classifier_applies_the_frozen_schema_and_semantic_rules():
    assert runner.classify_response(2, 7, _resp())[0] == "OK"
    assert runner.classify_response(2, 7, "not json")[0] == "PARSE_FAIL"
    assert runner.classify_response(2, 7, _resp(extra=1))[0] == "SCHEMA_FAIL"
    assert runner.classify_response(2, 8, _resp())[0] == "SCHEMA_FAIL"            # case-id echo
    assert runner.classify_response(2, 7, _resp(gate_a="RIGHT_PAPER"))[0] == "SEMANTIC_FAIL"
    # gate_d contradicting the deterministic element collapse is a content failure, never a label
    el = {k: "SAME" for k in runner.ELEMENT_KEYS} | {"metric": "DIFFERENT"}
    status, _, parsed = runner.classify_response(2, 7, _resp(elements=el, gate_d="NO_MATERIAL_CHANGE"))
    assert status == "SEMANTIC_FAIL" and parsed["gate_d"] == "NO_MATERIAL_CHANGE"
    assert runner.gate_d_collapse(el, "NONE", "NONE", "NONE") == "MATERIAL_CHANGE"


def test_journal_scan_rejects_duplicate_terminals_and_gaps(tmp_path):
    def journal(recs):
        p = tmp_path / "j.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        return p
    rec = {"case_id": 1, "arm": 1, "model": "gpt-5.4", "prompt_sha256": "h", "status": "OK", "terminal": True}
    term, resume = runner.scan_journal(journal([{**rec, "attempt": 1}]))
    assert list(term) == [(1, 1, "gpt-5.4")] and resume == {}
    with pytest.raises(runner.JournalIntegrityError, match="terminal"):
        runner.scan_journal(journal([{**rec, "attempt": 1}, {**rec, "attempt": 2}]))
    with pytest.raises(runner.JournalIntegrityError, match="contiguous"):
        runner.scan_journal(journal([{**rec, "attempt": 2}]))


def test_cell_plan_is_the_seeded_permutation_of_all_582_cells():
    plan = runner.ordered_plan(pd.DataFrame({"case_id": range(1, 98)}))
    assert len(plan) == len(set(plan)) == 582
    assert plan == runner.ordered_plan(pd.DataFrame({"case_id": range(1, 98)}))
    assert {m for _, _, m in plan} == set(runner.MODELS) and runner.ORDER_SEED == 20260818
