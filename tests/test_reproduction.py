"""Analysis reproduction from the distributed categorical data, compared with approved aggregates."""
import json

import pytest

import reproduce_analyses as ra

REQUIRED = {"G2-table2", "G2-ledger", "G2-weighted", "G2-weighted-ledger", "CAS-marginals", "CAS-nested",
            "CAS-nested-display", "CAS-D-elements", "CAS-D-crosstab", "CAS-ledger", "G5-completeness",
            "G5-primary_effects", "G5-mechanism_by_human_gate_a", "G5-gate_a_and_conditional_d",
            "G5-status_coverage", "G5-wrong_paper_arm2_responses", "G5-S4A", "G5-S4B", "G5-ledger"}
# Files that analyses READ; a check must never use one of them as its own comparison target.
ANALYSIS_INPUTS = {"data/signed_release/benchmark/g5_cells_source_text_free.csv",
                   "data/signed_release/benchmark/cascade_labels.csv",
                   "data/signed_release/benchmark/sampling_weights_observed.csv"}


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("repro")
    rep = ra.run_all(out)
    assert (out / "reproduction_report.json").exists()
    return rep


def test_every_reproduction_check_passes(report):
    failed = [r for r in report["checks"] if not r["pass"]]
    assert failed == [], json.dumps(failed, indent=1)[:4000]
    assert REQUIRED <= {r["id"] for r in report["checks"]}


def test_checks_compare_against_independent_approved_outputs(report):
    for r in report["checks"]:
        assert r["approved_source"] not in ANALYSIS_INPUTS, r["id"]


def test_bootstrap_interval_requires_the_frozen_cell_order(report):
    """The released interval is reproduced only under the frozen seed-20260818 cell plan; case-id order
    changes at least one bound, so the order is part of the pinned contract."""
    note = report["notes"]["bootstrap_order_note"]
    assert note["gpt-5.4"]["frozen_plan_order_ci"] != note["gpt-5.4"]["case_id_order_ci"]
    assert round(note["gpt-5.4"]["frozen_plan_order_ci"][0], 4) == 0.3918
