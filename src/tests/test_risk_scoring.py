"""
Phase 4 tests: site risk scoring.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v

Most tests build tiny deviation tables by hand so the expected points can be
worked out on paper. With the default config:
    Major 10, Minor 4, Administrative 1
    bonus: dose +5, prohibited medication +7, missed/out-of-window +3
    repeated pattern +5, score cap 25 points per patient
"""

import pandas as pd
import pytest

import config
from core.risk_scoring import (
    FACTOR_DOSING,
    FACTOR_PROHIBITED_MEDICATION,
    FACTOR_REPEATED_PATTERNS,
    FACTOR_VISIT_TIMING,
    SITE_RISK_COLUMNS,
    RiskScoringError,
    calculate_site_risk,
    check_scoring_config,
    deviation_points,
    find_repeated_patterns,
    risk_level,
    run_risk_analysis,
    score_from_points_per_patient,
    top_risk_factors,
)

MAJOR, MINOR, ADMIN = config.MAJOR, config.MINOR, config.ADMINISTRATIVE
DOSE = config.INCORRECT_DOSE
MED = config.PROHIBITED_MEDICATION
MISSED = config.MISSED_VISIT
WINDOW = config.OUT_OF_WINDOW_VISIT
DOC = config.MISSING_DOCUMENTATION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def deviations(*items):
    """deviations(("SITE-A", "P1", DOSE, MAJOR), ...) -> classified deviations table."""
    rows = [
        {"patient_id": patient, "site_id": site, "visit": "Visit 2",
         "deviation_type": deviation_type, "severity": severity}
        for site, patient, deviation_type, severity in items
    ]
    return pd.DataFrame(rows, columns=["patient_id", "site_id", "visit", "deviation_type", "severity"])


def patients(site_sizes):
    """patients({"SITE-A": 2}) -> patient table with PT IDs per site."""
    rows = [
        {"patient_id": f"{site}-P{number}", "site_id": site}
        for site, size in site_sizes.items()
        for number in range(1, size + 1)
    ]
    return pd.DataFrame(rows)


def site_row(site_risk, site_id):
    return site_risk.set_index("site_id").loc[site_id]


def score_one(site_size, *items):
    """Score a single site called SITE-A."""
    return site_row(calculate_site_risk(deviations(*items), patients({"SITE-A": site_size})), "SITE-A")


@pytest.fixture(scope="module")
def demo():
    return run_risk_analysis()["site_risk"]


# ---------------------------------------------------------------------------
# Points per deviation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "severity, expected",
    [(MAJOR, 10), (MINOR, 4), (ADMIN, 1)],
)
def test_severity_weights(severity, expected):
    # Missing documentation has no type bonus, so only severity points count
    assert deviation_points(severity, DOC) == expected


@pytest.mark.parametrize(
    "deviation_type, severity, expected",
    [
        (DOSE, MAJOR, 15),     # 10 + 5 dosing bonus
        (MED, MAJOR, 17),      # 10 + 7 prohibited medication bonus
        (MISSED, MAJOR, 13),   # 10 + 3 visit bonus
        (WINDOW, MAJOR, 13),   # 10 + 3
        (WINDOW, MINOR, 7),    # 4 + 3
        (WINDOW, ADMIN, 4),    # 1 + 3
        (DOC, ADMIN, 1),       # 1 + 0
    ],
)
def test_type_bonuses(deviation_type, severity, expected):
    assert deviation_points(severity, deviation_type) == expected


def test_dosing_bonus_in_site_total():
    with_bonus = score_one(1, ("SITE-A", "P1", DOSE, MAJOR))
    without_bonus = score_one(1, ("SITE-A", "P1", DOC, MAJOR))
    assert with_bonus["total_points"] - without_bonus["total_points"] == 5


def test_prohibited_medication_bonus_in_site_total():
    with_bonus = score_one(1, ("SITE-A", "P1", MED, MAJOR))
    without_bonus = score_one(1, ("SITE-A", "P1", DOC, MAJOR))
    assert with_bonus["total_points"] - without_bonus["total_points"] == 7


@pytest.mark.parametrize("visit_type", [MISSED, WINDOW])
def test_late_or_missed_visit_bonus_in_site_total(visit_type):
    with_bonus = score_one(1, ("SITE-A", "P1", visit_type, MINOR))
    without_bonus = score_one(1, ("SITE-A", "P1", DOC, MINOR))
    assert with_bonus["total_points"] - without_bonus["total_points"] == 3


def test_unknown_severity_raises():
    with pytest.raises(RiskScoringError, match="SEVERITY_POINTS"):
        deviation_points("Critical", DOSE)


# ---------------------------------------------------------------------------
# Repeated patterns
# ---------------------------------------------------------------------------
def test_same_type_in_two_patients_is_a_repeated_pattern():
    site = score_one(2, ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR))
    assert site["repeated_patterns"] == 1
    assert site["repeated_pattern_types"] == DOSE
    assert site["total_points"] == 15 + 15 + 5


def test_same_type_twice_in_one_patient_is_not_a_repeated_pattern():
    site = score_one(1, ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P1", DOSE, MAJOR))
    assert site["repeated_patterns"] == 0
    assert site["total_points"] == 30


def test_each_repeated_type_earns_its_own_bonus():
    site = score_one(
        2,
        ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR),
        ("SITE-A", "P1", WINDOW, ADMIN), ("SITE-A", "P2", WINDOW, ADMIN),
    )
    assert site["repeated_patterns"] == 2
    assert site["total_points"] == 15 + 15 + 4 + 4 + 5 + 5


def test_same_type_at_different_sites_is_not_a_pattern():
    table = deviations(("SITE-A", "P1", DOSE, MAJOR), ("SITE-B", "P2", DOSE, MAJOR))
    assert find_repeated_patterns(table).empty


def test_repeated_pattern_minimum_follows_config(monkeypatch):
    monkeypatch.setattr(config, "REPEATED_PATTERN_MIN_PATIENTS", 3)
    site = score_one(2, ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR))
    assert site["repeated_patterns"] == 0


# ---------------------------------------------------------------------------
# Normalisation, capping and levels
# ---------------------------------------------------------------------------
def test_site_size_normalisation():
    items = [("SITE-A", "P1", DOSE, MAJOR)]  # 15 points
    small = score_one(1, *items)
    large = score_one(3, *items)
    assert small["points_per_patient"] == 15
    assert large["points_per_patient"] == 5
    assert small["risk_score"] == 60   # 15 / 25 * 100
    assert large["risk_score"] == 20   # 5 / 25 * 100


def test_score_is_capped_at_100():
    site = score_one(1, *[("SITE-A", "P1", MED, MAJOR)] * 3)  # 51 points per patient
    assert site["points_per_patient"] == 51
    assert site["risk_score"] == 100
    assert site["risk_level"] == "HIGH"


@pytest.mark.parametrize(
    "points_per_patient, expected_score",
    [(0, 0), (7.5, 30), (7.6, 30), (7.625, 31), (15, 60), (15.25, 61), (25, 100), (80, 100)],
)
def test_score_scaling_and_rounding(points_per_patient, expected_score):
    assert score_from_points_per_patient(points_per_patient) == expected_score


@pytest.mark.parametrize(
    "score, expected_level",
    [(0, "LOW"), (30, "LOW"), (31, "MEDIUM"), (60, "MEDIUM"), (61, "HIGH"), (100, "HIGH")],
)
def test_risk_level_boundaries(score, expected_level):
    assert risk_level(score) == expected_level


def test_low_boundary_end_to_end():
    site = score_one(2, ("SITE-A", "P1", DOSE, MAJOR))  # 15 / 2 = 7.5 -> 30
    assert (site["risk_score"], site["risk_level"]) == (30, "LOW")


def test_medium_boundary_end_to_end():
    site = score_one(1, ("SITE-A", "P1", DOSE, MAJOR))  # 15 / 1 = 15 -> 60
    assert (site["risk_score"], site["risk_level"]) == (60, "MEDIUM")


def test_high_boundary_end_to_end():
    # 15 + 1 = 16 points -> 64; the smallest step above 60 possible with one patient
    site = score_one(1, ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P1", DOC, ADMIN))
    assert (site["risk_score"], site["risk_level"]) == (64, "HIGH")


def test_score_cap_follows_config(monkeypatch):
    monkeypatch.setattr(config, "SCORE_CAP_POINTS_PER_PATIENT", 20)
    site = score_one(1, ("SITE-A", "P1", DOSE, MAJOR))  # 15 / 20 = 75
    assert site["risk_score"] == 75


# ---------------------------------------------------------------------------
# Whole table
# ---------------------------------------------------------------------------
def test_empty_deviations_score_every_site_zero():
    site_risk = calculate_site_risk(deviations(), patients({"SITE-A": 3, "SITE-B": 5}))
    assert list(site_risk.columns) == SITE_RISK_COLUMNS
    assert len(site_risk) == 2
    assert (site_risk["risk_score"] == 0).all()
    assert (site_risk["risk_level"] == "LOW").all()
    assert (site_risk["top_risk_factors"] == "None").all()


def test_no_patients_gives_empty_table():
    site_risk = calculate_site_risk(deviations(), pd.DataFrame(columns=["patient_id", "site_id"]))
    assert site_risk.empty
    assert list(site_risk.columns) == SITE_RISK_COLUMNS


def test_one_clean_site():
    site = score_one(10)
    assert site["total_deviations"] == 0
    assert site["total_points"] == 0
    assert (site["risk_score"], site["risk_level"]) == (0, "LOW")


def test_one_high_risk_site_breakdown():
    site = score_one(
        2,
        ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR),
        ("SITE-A", "P1", MED, MAJOR),
        ("SITE-A", "P2", MISSED, MAJOR),
        ("SITE-A", "P2", WINDOW, MINOR),
        ("SITE-A", "P1", DOC, ADMIN),
    )
    assert site["patients"] == 2
    assert site["total_deviations"] == 6
    assert (site["major_deviations"], site["minor_deviations"], site["administrative_deviations"]) == (4, 1, 1)
    assert site["dosing_errors"] == 2
    assert site["prohibited_medication_incidents"] == 1
    assert site["late_or_missed_visits"] == 2
    assert site["repeated_patterns"] == 1  # dosing in P1 and P2
    # 15 + 15 + 17 + 13 + 7 + 1 + 5 = 73 points, 36.5 per patient, 146 -> capped
    assert site["total_points"] == 73
    assert site["points_per_patient"] == 36.5
    assert (site["risk_score"], site["risk_level"]) == (100, "HIGH")


def test_factor_points_add_up_to_total_points():
    site = score_one(
        2,
        ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR),
        ("SITE-A", "P1", MED, MAJOR), ("SITE-A", "P2", WINDOW, MINOR), ("SITE-A", "P1", DOC, ADMIN),
    )
    assert site["dosing_points"] == 30
    assert site["prohibited_medication_points"] == 17
    assert site["visit_timing_points"] == 7
    assert site["documentation_points"] == 1
    assert site["repeated_pattern_points"] == 5
    factor_total = (site["dosing_points"] + site["prohibited_medication_points"] + site["visit_timing_points"]
                    + site["documentation_points"] + site["repeated_pattern_points"])
    assert factor_total == site["total_points"] == 60


def test_multiple_sites_sorted_highest_risk_first():
    table = deviations(
        ("ALPHA", "A1", WINDOW, ADMIN),
        ("BRAVO", "B1", DOSE, MAJOR), ("BRAVO", "B2", MED, MAJOR),
        ("CHARLIE", "C1", MISSED, MAJOR),
    )
    site_risk = calculate_site_risk(table, patients({"ALPHA": 2, "BRAVO": 2, "CHARLIE": 2, "DELTA": 2}))
    assert list(site_risk["site_id"]) == ["BRAVO", "CHARLIE", "ALPHA", "DELTA"]
    assert list(site_risk["risk_score"]) == [64, 26, 8, 0]   # 16, 6.5, 2, 0 points per patient
    assert list(site_risk["risk_level"]) == ["HIGH", "LOW", "LOW", "LOW"]


def test_deviation_at_site_without_patients_raises():
    with pytest.raises(RiskScoringError, match="SITE-X"):
        calculate_site_risk(deviations(("SITE-X", "P1", DOSE, MAJOR)), patients({"SITE-A": 1}))


def test_deviations_without_severity_raise():
    table = deviations(("SITE-A", "P1", DOSE, MAJOR)).drop(columns=["severity"])
    with pytest.raises(RiskScoringError, match="add_severity"):
        calculate_site_risk(table, patients({"SITE-A": 1}))


# ---------------------------------------------------------------------------
# Top contributing factors
# ---------------------------------------------------------------------------
def test_top_risk_factors_biggest_first_and_zero_factors_left_out():
    site = score_one(
        2,
        ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR),   # 30 dosing + 5 pattern
        ("SITE-A", "P1", MED, MAJOR),                                   # 17
    )
    factors = top_risk_factors(site)
    assert [item["factor"] for item in factors] == [FACTOR_DOSING, FACTOR_PROHIBITED_MEDICATION, FACTOR_REPEATED_PATTERNS]
    assert [item["points"] for item in factors] == [30, 17, 5]
    assert [item["share_pct"] for item in factors] == [58, 33, 10]
    assert site["top_risk_factors"] == (
        "Dosing errors: 30 pts (58%); Prohibited medications: 17 pts (33%); Repeated patterns: 5 pts (10%)"
    )


def test_top_risk_factors_count_is_limited():
    site = score_one(
        2,
        ("SITE-A", "P1", DOSE, MAJOR), ("SITE-A", "P2", DOSE, MAJOR),
        ("SITE-A", "P1", MED, MAJOR), ("SITE-A", "P1", WINDOW, MINOR), ("SITE-A", "P2", DOC, ADMIN),
    )
    assert len(top_risk_factors(site)) == config.TOP_RISK_FACTORS_COUNT == 3
    assert len(top_risk_factors(site, count=5)) == 5


def test_clean_site_has_no_top_factors():
    assert top_risk_factors(score_one(4)) == []


# ---------------------------------------------------------------------------
# Configuration checks
# ---------------------------------------------------------------------------
def test_default_scoring_config_is_valid():
    check_scoring_config()


def test_zero_score_cap_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "SCORE_CAP_POINTS_PER_PATIENT", 0)
    with pytest.raises(RiskScoringError, match="SCORE_CAP_POINTS_PER_PATIENT"):
        check_scoring_config()


def test_unordered_risk_levels_are_rejected(monkeypatch):
    monkeypatch.setattr(config, "RISK_LEVELS", [("LOW", 60), ("MEDIUM", 30), ("HIGH", 100)])
    with pytest.raises(RiskScoringError, match="RISK_LEVELS"):
        check_scoring_config()


# ---------------------------------------------------------------------------
# Synthetic demo dataset
# ---------------------------------------------------------------------------
def test_demo_scores_every_site(demo):
    assert len(demo) == 10
    assert demo["risk_score"].between(0, 100).all()


def test_demo_problem_sites_are_the_two_highest(demo):
    assert list(demo["site_id"][:2]) == ["SITE-104", "SITE-107"]


def test_demo_site_104(demo):
    site = site_row(demo, "SITE-104")
    assert site["total_points"] == 205
    assert (site["risk_score"], site["risk_level"]) == (68, "HIGH")
    assert top_risk_factors(site)[0]["factor"] == FACTOR_DOSING
    assert top_risk_factors(site)[1]["factor"] == FACTOR_PROHIBITED_MEDICATION


def test_demo_site_107(demo):
    site = site_row(demo, "SITE-107")
    assert site["total_points"] == 157
    assert (site["risk_score"], site["risk_level"]) == (52, "MEDIUM")
    assert top_risk_factors(site)[0]["factor"] == FACTOR_VISIT_TIMING


@pytest.mark.parametrize("site_id", ["SITE-105", "SITE-110"])
def test_demo_clean_sites(demo, site_id):
    site = site_row(demo, site_id)
    assert (site["total_deviations"], site["risk_score"], site["risk_level"]) == (0, 0, "LOW")


def test_demo_other_sites_are_low(demo):
    others = demo[~demo["site_id"].isin(["SITE-104", "SITE-107"])]
    assert (others["risk_level"] == "LOW").all()
