"""Fail-closed input handling, invalid-first scoring and denominator separation."""
import pandas as pd
import pytest

import g5_analyze as ga
import g5_build_release as g5r
import reproduce_analyses as ra

CELLS = ra.BENCH / "g5_cells_source_text_free.csv"


def _cells():
    return pd.read_csv(CELLS, dtype={"model_gate_a": str, "model_gate_d": str})


def _flip_one_reference_row(d):
    """Give one row of case 1 a different human label from the rest of that case."""
    i = d.index[d.case_id == 1][0]
    d = d.copy()
    d.loc[i, "human_reference_label"] = ("NO_DISCREPANCY" if d.loc[i, "human_reference_label"] == "GENUINE_DISCREPANCY"
                                         else "GENUINE_DISCREPANCY")
    return d


def _write(tmp_path, df, name="cells.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def test_unchanged_cells_load():
    cells, ref, pub = ra.load_public_cells(CELLS)
    assert len(cells) == 582 and len(ref) == 97


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.drop(columns="correct"), "unexpected cell columns"),
    (lambda d: d.assign(extra_text="x"), "unexpected cell columns"),
    (lambda d: d.assign(arm=d.arm.astype(str) + "a"), "not integer-valued"),
    (lambda d: d.assign(terminal_status=d.terminal_status.where(d.index > 0, "REFUSED")), "unknown terminal status"),
    (lambda d: d.drop(index=5), "frozen input validation"),                                   # missing cell
    (lambda d: pd.concat([d, d.iloc[[5]]]), "duplicate"),                                      # duplicate cell
    (lambda d: d.assign(model_identifier=d.model_identifier.where(d.index > 0, "other-model")), "frozen input validation"),
    (lambda d: d.assign(model_gate_d=d.model_gate_d.where(d.index > 0, "MAYBE")), "frozen input validation"),
    (lambda d: _flip_one_reference_row(d), "more than one human reference label"),
])
def test_malformed_missing_duplicate_or_unknown_cells_fail_closed(tmp_path, mutate, msg):
    with pytest.raises(ra.ReproductionError, match=msg):
        ra.load_public_cells(_write(tmp_path, mutate(_cells())))


def test_released_correct_column_is_never_trusted(tmp_path):
    d = _cells()
    d.loc[0, "correct"] = 1 - d.loc[0, "correct"]
    cells, ref, pub = ra.load_public_cells(_write(tmp_path, d))
    with pytest.raises(ra.ReproductionError, match="disagrees with the released"):
        ra.recompute_correctness(cells, ref, pub)


@pytest.mark.parametrize("status", ["SCHEMA_FAIL", "SEMANTIC_FAIL", "TRANSPORT_FAIL", "PARSE_FAIL"])
def test_invalid_first_scoring_even_with_a_partially_parsed_positive(status):
    assert ga.derive_bottom_line(2, status, None, "MATERIAL_CHANGE") == "INDETERMINATE"
    assert ga.derive_bottom_line(1, status, "RIGHT_PAPER", "MATERIAL_CHANGE") == "INDETERMINATE"
    if status != "PARSE_FAIL":
        assert g5r.classify_arm2_response(status, "MATERIAL_CHANGE", "INDETERMINATE") == "invalid"


def test_real_partially_parsed_invalid_cells_stay_invalid():
    cells, ref, pub = ra.load_public_cells(CELLS)
    df = ra.recompute_correctness(cells, ref, pub)
    bad = df[(df.arm == 2) & (df.ref_gate_a == "WRONG_PAPER") & (df.status != "OK")]
    assert len(bad) == 8 and (bad.gate_d == "MATERIAL_CHANGE").sum() == 5
    assert (bad.bl == "INDETERMINATE").all() and (bad.correct == 0).all()
    assert int(g5r.table_wrong_paper_arm2_responses(df).invalid.sum()) == 8


def test_denominator_families_are_computed_separately_and_never_joined():
    ra.assert_families_separate([97, 45, 30, 13, 14, 2], [83, 32, 17, 7, 8, 2], 83)
    with pytest.raises(ra.ReproductionError, match="mixed"):
        ra.assert_families_separate([97, 45, 30, 13, 14, 2], [83, 45, 30, 13, 14, 2], 83)
    with pytest.raises(ra.ReproductionError, match="mixed"):
        ra.assert_families_separate([97, 45, 30, 13, 14, 2], [97, 45, 30, 13, 14, 2], 83)


def test_inconsistent_weights_are_rejected(tmp_path):
    w = pd.read_csv(ra.BENCH / "sampling_weights_observed.csv")
    w.loc[0, "inverse_probability_weight_mc"] *= 1.01
    with pytest.raises(ra.ReproductionError, match="inconsistent"):
        ra.load_cascade(weights=_write(tmp_path, w, "w.csv"))


def test_frozen_plan_order_rejects_an_incomplete_plan():
    cells, ref, pub = ra.load_public_cells(CELLS)
    with pytest.raises(ra.ReproductionError, match="frozen 582-cell plan"):
        ra.frozen_plan_order(cells.iloc[1:])
