"""
Phase 4 tests: early warning detection.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v

The protocol has 4 visits, so "early" = Visit 1-2 and "later" = Visit 3-4.
"""

import pandas as pd
import pytest

import config
from core.early_warning import (
    HIGH_DEVIATION_RATE,
    INCREASING_TREND,
    REPEATED_DOSING,
    REPEATED_PROHIBITED_MEDICATION,
    SITE_WARNING_COLUMNS,
    WARNING_COLUMNS,
    build_headline,
    deviation_rates,
    detect_early_warnings,
    is_increasing_trend,
    split_visits,
    summarize_site_warnings,
)
from core.risk_scoring import calculate_site_risk, run_risk_analysis
from utils.data_loader import load_protocol

MAJOR, MINOR, ADMIN = config.MAJOR, config.MINOR, config.ADMINISTRATIVE
DOSE = config.INCORRECT_DOSE
MED = config.PROHIBITED_MEDICATION
WINDOW = config.OUT_OF_WINDOW_VISIT
DOC = config.MISSING_DOCUMENTATION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def protocol():
    return load_protocol()


def deviations(*items):
    """deviations(("SITE-A", "P1", DOSE, MAJOR, "Visit 2"), ...)"""
    rows = [
        {"patient_id": patient, "site_id": site, "visit": visit, "deviation_type": deviation_type, "severity": severity}
        for site, patient, deviation_type, severity, visit in items
    ]
    return pd.DataFrame(rows, columns=["patient_id", "site_id", "visit", "deviation_type", "severity"])


def patients(site_sizes):
    return pd.DataFrame([
        {"patient_id": f"{site}-P{number}", "site_id": site}
        for site, size in site_sizes.items()
        for number in range(1, size + 1)
    ])


def analyse(table, site_sizes, protocol):
    site_risk = calculate_site_risk(table, patients(site_sizes))
    warnings = detect_early_warnings(site_risk, table, protocol)
    return site_risk, warnings


def warning_types(warnings, site_id):
    return set(warnings.loc[warnings["site_id"] == site_id, "warning_type"])


def repeat(site, deviation_type, severity, visits, patient_prefix="P"):
    """One deviation per visit in `visits`, each for a different patient."""
    return [(site, f"{patient_prefix}{i}", deviation_type, severity, visit) for i, visit in enumerate(visits, start=1)]


@pytest.fixture(scope="module")
def demo():
    analysis = run_risk_analysis()
    warnings = detect_early_warnings(analysis["site_risk"], analysis["deviations"], analysis["protocol"])
    return {"site_risk": analysis["site_risk"], "warnings": warnings,
            "summary": summarize_site_warnings(analysis["site_risk"], warnings)}


# ---------------------------------------------------------------------------
# A. Repeated dosing errors
# ---------------------------------------------------------------------------
def test_two_dosing_errors_trigger_warning(protocol):
    table = deviations(*repeat("SITE-A", DOSE, MAJOR, ["Visit 2", "Visit 3"]))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_DOSING in warning_types(warnings, "SITE-A")
    message = warnings.loc[warnings["warning_type"] == REPEATED_DOSING, "message"].iloc[0]
    assert message == "2 dosing errors across 2 patient(s) (warning starts at 2)."


def test_two_dosing_errors_in_the_same_patient_still_trigger(protocol):
    table = deviations(("SITE-A", "P1", DOSE, MAJOR, "Visit 2"), ("SITE-A", "P1", DOSE, MAJOR, "Visit 3"))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_DOSING in warning_types(warnings, "SITE-A")


def test_one_dosing_error_does_not_trigger(protocol):
    table = deviations(("SITE-A", "P1", DOSE, MAJOR, "Visit 2"))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_DOSING not in warning_types(warnings, "SITE-A")


# ---------------------------------------------------------------------------
# B. Repeated prohibited medications
# ---------------------------------------------------------------------------
def test_two_prohibited_medications_trigger_warning(protocol):
    table = deviations(*repeat("SITE-A", MED, MAJOR, ["Visit 2", "Visit 3"]))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_PROHIBITED_MEDICATION in warning_types(warnings, "SITE-A")


def test_one_prohibited_medication_does_not_trigger(protocol):
    table = deviations(("SITE-A", "P1", MED, MAJOR, "Visit 2"))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_PROHIBITED_MEDICATION not in warning_types(warnings, "SITE-A")


def test_repeated_thresholds_follow_config(monkeypatch, protocol):
    monkeypatch.setattr(config, "WARNING_REPEATED_DOSING_MIN", 3)
    table = deviations(*repeat("SITE-A", DOSE, MAJOR, ["Visit 2", "Visit 3"]))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert REPEATED_DOSING not in warning_types(warnings, "SITE-A")


# ---------------------------------------------------------------------------
# C. Increasing trend
# ---------------------------------------------------------------------------
def test_split_visits_uses_first_and_second_half(protocol):
    assert split_visits(protocol) == (["Visit 1", "Visit 2"], ["Visit 3", "Visit 4"])


def test_split_visits_with_odd_number_leaves_out_middle_visit():
    five_visits = {"visits": [{"visit": f"V{n}"} for n in range(1, 6)]}
    assert split_visits(five_visits) == (["V1", "V2"], ["V4", "V5"])


@pytest.mark.parametrize(
    "early, later, expected",
    [
        (0, 3, True),    # from nothing to 3
        (1, 4, True),
        (2, 13, True),
        (3, 6, True),    # exactly 2x and +3
        (0, 2, False),   # increase of only 2
        (2, 4, False),   # 2x but increase of only 2
        (3, 5, False),   # not 2x
        (5, 5, False),   # flat
        (6, 1, False),   # decreasing
    ],
)
def test_is_increasing_trend(early, later, expected):
    assert is_increasing_trend(early, later) is expected


def test_increasing_trend_warning_on_site(protocol):
    table = deviations(
        *repeat("SITE-A", WINDOW, ADMIN, ["Visit 2"]),
        *repeat("SITE-A", WINDOW, MINOR, ["Visit 3", "Visit 3", "Visit 4", "Visit 4"], patient_prefix="Q"),
    )
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert INCREASING_TREND in warning_types(warnings, "SITE-A")
    message = warnings.loc[warnings["warning_type"] == INCREASING_TREND, "message"].iloc[0]
    assert message == "Deviations rose from 1 at early visits (Visit 1, Visit 2) to 4 at later visits (Visit 3, Visit 4)."


def test_decreasing_deviations_do_not_trigger_trend(protocol):
    table = deviations(*repeat("SITE-A", WINDOW, MINOR, ["Visit 1", "Visit 1", "Visit 2", "Visit 2", "Visit 4"]))
    _, warnings = analyse(table, {"SITE-A": 10}, protocol)
    assert INCREASING_TREND not in warning_types(warnings, "SITE-A")


# ---------------------------------------------------------------------------
# D. Unusually high deviation rate
# ---------------------------------------------------------------------------
def test_high_deviation_rate_warning(protocol):
    # 3 sites x 1 patient x 4 visits = 12 expected visits; 3 deviations -> study rate 0.25
    # SITE-A: 3 / 4 = 0.75 = 3x the study rate
    table = deviations(*repeat("SITE-A", DOC, ADMIN, ["Visit 1", "Visit 2", "Visit 3"]))
    site_risk, warnings = analyse(table, {"SITE-A": 1, "SITE-B": 1, "SITE-C": 1}, protocol)

    rates, study_rate = deviation_rates(site_risk, protocol)
    assert study_rate == 0.25
    assert HIGH_DEVIATION_RATE in warning_types(warnings, "SITE-A")
    assert warning_types(warnings, "SITE-B") == set()
    message = warnings.loc[warnings["warning_type"] == HIGH_DEVIATION_RATE, "message"].iloc[0]
    assert message == "0.75 deviations per expected visit (3 across 4 visits), 3.0x the study average of 0.25."


def test_rate_exactly_twice_average_does_not_trigger(protocol):
    # 2 sites x 1 patient: study rate 2/8 = 0.25; SITE-A 2/4 = 0.5 = exactly 2x
    table = deviations(*repeat("SITE-A", DOC, ADMIN, ["Visit 1", "Visit 2"]))
    _, warnings = analyse(table, {"SITE-A": 1, "SITE-B": 1}, protocol)
    assert HIGH_DEVIATION_RATE not in warning_types(warnings, "SITE-A")


def test_rate_uses_expected_visits_so_bigger_sites_are_fair(protocol):
    # Same 3 deviations: at a 1-patient site it's a high rate, at a 10-patient site it isn't
    table = deviations(
        *repeat("SITE-SMALL", DOC, ADMIN, ["Visit 1", "Visit 2", "Visit 3"]),
        *repeat("SITE-BIG", DOC, ADMIN, ["Visit 1", "Visit 2", "Visit 3"], patient_prefix="B"),
    )
    _, warnings = analyse(table, {"SITE-SMALL": 1, "SITE-BIG": 10, "SITE-C": 10}, protocol)
    assert HIGH_DEVIATION_RATE in warning_types(warnings, "SITE-SMALL")
    assert HIGH_DEVIATION_RATE not in warning_types(warnings, "SITE-BIG")


# ---------------------------------------------------------------------------
# Empty data, clean sites, and warnings not changing scores
# ---------------------------------------------------------------------------
def test_no_deviations_means_no_warnings(protocol):
    site_risk, warnings = analyse(deviations(), {"SITE-A": 5, "SITE-B": 5}, protocol)
    assert warnings.empty
    assert list(warnings.columns) == WARNING_COLUMNS
    summary = summarize_site_warnings(site_risk, warnings)
    assert list(summary.columns) == SITE_WARNING_COLUMNS
    assert (summary["headline"] == "No deviations detected; no early warning signals.").all()


def test_empty_site_table_gives_empty_warnings(protocol):
    empty = calculate_site_risk(deviations(), pd.DataFrame(columns=["patient_id", "site_id"]))
    assert detect_early_warnings(empty, deviations(), protocol).empty


def test_warnings_do_not_change_risk_scores(protocol):
    table = deviations(*repeat("SITE-A", DOSE, MAJOR, ["Visit 2", "Visit 3", "Visit 4"]))
    site_risk = calculate_site_risk(table, patients({"SITE-A": 5, "SITE-B": 5}))
    before = site_risk.copy()
    warnings = detect_early_warnings(site_risk, table, protocol)
    summarize_site_warnings(site_risk, warnings)
    assert not warnings.empty
    pd.testing.assert_frame_equal(site_risk, before)


# ---------------------------------------------------------------------------
# E. Top factors in the headline
# ---------------------------------------------------------------------------
def test_headline_names_top_factors_and_repeated_warnings(protocol):
    table = deviations(
        *repeat("SITE-A", DOSE, MAJOR, ["Visit 2", "Visit 3", "Visit 4"]),
        *repeat("SITE-A", MED, MAJOR, ["Visit 3", "Visit 4"], patient_prefix="M"),
    )
    site_risk, warnings = analyse(table, {"SITE-A": 3}, protocol)
    summary = summarize_site_warnings(site_risk, warnings).set_index("site_id")
    assert summary.loc["SITE-A", "headline"].startswith(
        "Repeated dosing deviations and repeated prohibited medication incidents are driving elevated site risk."
    )


def test_headline_for_low_site_without_warnings():
    site = {"total_points": 4, "risk_level": "LOW", "dosing_points": 0, "prohibited_medication_points": 0,
            "visit_timing_points": 4, "documentation_points": 0, "repeated_pattern_points": 0}
    assert build_headline(site, []) == (
        "Late or missed visits are the main contributors to low site risk. No early warning signals."
    )


def test_headline_mentions_increasing_trend():
    site = {"total_points": 50, "risk_level": "MEDIUM", "dosing_points": 0, "prohibited_medication_points": 0,
            "visit_timing_points": 45, "documentation_points": 0, "repeated_pattern_points": 5}
    assert build_headline(site, [INCREASING_TREND]) == (
        "Late or missed visits are driving moderate site risk. Deviations are increasing at later visits."
    )


# ---------------------------------------------------------------------------
# Synthetic demo dataset
# ---------------------------------------------------------------------------
def test_demo_site_104_warnings(demo):
    assert warning_types(demo["warnings"], "SITE-104") == {
        REPEATED_DOSING, REPEATED_PROHIBITED_MEDICATION, INCREASING_TREND, HIGH_DEVIATION_RATE,
    }
    headline = demo["summary"].set_index("site_id").loc["SITE-104", "headline"]
    assert headline.startswith(
        "Repeated dosing deviations and repeated prohibited medication incidents are driving elevated site risk."
    )


def test_demo_site_107_warnings(demo):
    assert warning_types(demo["warnings"], "SITE-107") == {INCREASING_TREND, HIGH_DEVIATION_RATE}
    warnings = demo["warnings"]
    selected = (warnings["site_id"] == "SITE-107") & (warnings["warning_type"] == INCREASING_TREND)
    message = warnings.loc[selected, "message"].iloc[0]
    assert "from 2 at early visits" in message and "to 13 at later visits" in message


@pytest.mark.parametrize("site_id", ["SITE-105", "SITE-110"])
def test_demo_clean_sites_have_no_warnings(demo, site_id):
    assert warning_types(demo["warnings"], site_id) == set()


def test_demo_warning_sites(demo):
    assert set(demo["warnings"]["site_id"]) == {"SITE-104", "SITE-106", "SITE-107"}
    assert warning_types(demo["warnings"], "SITE-106") == {INCREASING_TREND}
