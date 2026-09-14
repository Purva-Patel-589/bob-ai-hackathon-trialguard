"""
Phase 3 tests: severity classification.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v
"""

import io

import pandas as pd
import pytest

import config
from core.deviation_detector import DEVIATION_COLUMNS, detect_deviations, run_detection
from core.severity import (
    SeverityRuleError,
    add_severity,
    check_severity_config,
    classify_severity,
    summarize_severity,
)
from utils.data_loader import load_patients, load_protocol

COLUMNS = ["patient_id", "site_id", "visit", "actual_day", "dose_mg", "medication"]
ON_TIME_DAY = {"Visit 1": 0, "Visit 2": 14, "Visit 3": 28, "Visit 4": 56}


def patients_with(changes=None, skip_visits=()):
    """One compliant patient (4 on-time visits) with optional edits, loaded via the real loader."""
    changes = changes or {}
    lines = [",".join(COLUMNS)]
    for visit, day in ON_TIME_DAY.items():
        if visit in skip_visits:
            continue
        row = {"patient_id": "PT-1", "site_id": "SITE-A", "visit": visit,
               "actual_day": day, "dose_mg": 10, "medication": "None"}
        row.update(changes.get(visit, {}))
        lines.append(",".join(str(row[column]) for column in COLUMNS))
    return load_patients(io.StringIO("\n".join(lines) + "\n"))


@pytest.fixture(scope="module")
def protocol():
    return load_protocol()


@pytest.fixture(scope="module")
def demo():
    return add_severity(run_detection())


def classified_for(protocol, changes=None, skip_visits=()):
    return add_severity(detect_deviations(patients_with(changes, skip_visits), protocol))


# ---------------------------------------------------------------------------
# Fixed severities by deviation type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "deviation_type, expected",
    [
        (config.MISSED_VISIT, config.MAJOR),
        (config.INCORRECT_DOSE, config.MAJOR),
        (config.PROHIBITED_MEDICATION, config.MAJOR),
        (config.MISSING_DOCUMENTATION, config.ADMINISTRATIVE),
    ],
)
def test_fixed_severity_by_type(deviation_type, expected):
    severity, rule = classify_severity(deviation_type)
    assert severity == expected
    assert deviation_type in rule


# ---------------------------------------------------------------------------
# Out-of-window boundaries (defaults: 1-2 Administrative, 3-7 Minor, 8+ Major)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "days, expected",
    [
        (1, config.ADMINISTRATIVE),
        (2, config.ADMINISTRATIVE),
        (3, config.MINOR),
        (5, config.MINOR),
        (7, config.MINOR),
        (8, config.MAJOR),
        (13, config.MAJOR),
        (100, config.MAJOR),
    ],
)
def test_out_of_window_boundaries(days, expected):
    severity, _ = classify_severity(config.OUT_OF_WINDOW_VISIT, days)
    assert severity == expected


@pytest.mark.parametrize("days, expected", [(2.5, config.MINOR), (7.5, config.MAJOR)])
def test_part_days_fall_into_the_next_band(days, expected):
    assert classify_severity(config.OUT_OF_WINDOW_VISIT, days)[0] == expected


def test_out_of_window_rule_text_explains_the_band():
    assert classify_severity(config.OUT_OF_WINDOW_VISIT, 2)[1] == (
        "2 day(s) outside window: up to 2 days is Administrative"
    )
    assert classify_severity(config.OUT_OF_WINDOW_VISIT, 3)[1] == (
        "3 day(s) outside window: 3 to 7 days is Minor"
    )
    assert classify_severity(config.OUT_OF_WINDOW_VISIT, 8)[1] == (
        "8 day(s) outside window: more than 7 days is Major"
    )


@pytest.mark.parametrize(
    "day, days_outside, expected",
    [
        (17, 1, config.ADMINISTRATIVE),
        (18, 2, config.ADMINISTRATIVE),
        (19, 3, config.MINOR),
        (23, 7, config.MINOR),
        (24, 8, config.MAJOR),
        (4, 8, config.MAJOR),  # early visit: earliest allowed day is 12
    ],
)
def test_boundaries_end_to_end_through_detector(protocol, day, days_outside, expected):
    """Visit 2 is day 14 +/-2 (allowed 12-16)."""
    classified = classified_for(protocol, {"Visit 2": {"actual_day": day}})
    assert len(classified) == 1
    row = classified.iloc[0]
    assert row["days_outside_window"] == days_outside
    assert row["severity"] == expected


# ---------------------------------------------------------------------------
# Every type end to end through the detector
# ---------------------------------------------------------------------------
def test_missed_visit_no_record_is_major(protocol):
    classified = classified_for(protocol, skip_visits=["Visit 3"])
    assert list(classified["severity"]) == [config.MAJOR]


def test_missed_visit_blank_day_is_major(protocol):
    classified = classified_for(protocol, {"Visit 4": {"actual_day": "", "dose_mg": "", "medication": ""}})
    assert list(classified["severity"]) == [config.MAJOR]


def test_incorrect_dose_is_major(protocol):
    classified = classified_for(protocol, {"Visit 2": {"dose_mg": 20}})
    assert list(classified["severity"]) == [config.MAJOR]


def test_prohibited_medication_is_major(protocol):
    classified = classified_for(protocol, {"Visit 2": {"medication": "DrugC"}})
    assert list(classified["severity"]) == [config.MAJOR]


def test_missing_documentation_is_administrative(protocol):
    classified = classified_for(protocol, {"Visit 2": {"medication": ""}, "Visit 3": {"dose_mg": ""}})
    assert list(classified["severity"]) == [config.ADMINISTRATIVE, config.ADMINISTRATIVE]


def test_one_record_with_three_deviations_gets_three_severities(protocol):
    classified = classified_for(protocol, {"Visit 3": {"actual_day": 33, "dose_mg": 20, "medication": ""}})
    # Visit 3 allowed 25-31: day 33 is 2 days outside
    assert list(classified["deviation_type"]) == [
        config.OUT_OF_WINDOW_VISIT, config.INCORRECT_DOSE, config.MISSING_DOCUMENTATION,
    ]
    assert list(classified["severity"]) == [config.ADMINISTRATIVE, config.MAJOR, config.ADMINISTRATIVE]


# ---------------------------------------------------------------------------
# Output table
# ---------------------------------------------------------------------------
def test_existing_columns_are_preserved_and_severity_added(protocol):
    detected = detect_deviations(patients_with({"Visit 2": {"dose_mg": 20, "actual_day": 20}}), protocol)
    classified = add_severity(detected)

    expected_columns = DEVIATION_COLUMNS.copy()
    position = expected_columns.index("deviation_type") + 1
    expected_columns[position:position] = ["severity", "severity_rule"]
    assert list(classified.columns) == expected_columns

    pd.testing.assert_frame_equal(classified[DEVIATION_COLUMNS], detected)


def test_add_severity_does_not_change_the_input_table(protocol):
    detected = detect_deviations(patients_with({"Visit 2": {"dose_mg": 20}}), protocol)
    add_severity(detected)
    assert "severity" not in detected.columns


def test_empty_deviation_table_gets_severity_columns(protocol):
    classified = classified_for(protocol)
    assert classified.empty
    assert "severity" in classified.columns
    assert "severity_rule" in classified.columns


# ---------------------------------------------------------------------------
# Errors and configuration
# ---------------------------------------------------------------------------
def test_unknown_deviation_type_raises_clear_error():
    with pytest.raises(SeverityRuleError, match="SEVERITY_BY_DEVIATION_TYPE"):
        classify_severity("Made-up deviation")


@pytest.mark.parametrize("bad_days", [None, pd.NA, float("nan"), 0, -3])
def test_out_of_window_without_positive_days_raises(bad_days):
    with pytest.raises(SeverityRuleError, match="greater than 0"):
        classify_severity(config.OUT_OF_WINDOW_VISIT, bad_days)


def test_default_config_is_valid():
    check_severity_config()  # raises if invalid


def test_rules_follow_config_changes(monkeypatch):
    """Changing config.py values changes the classification - no code edits needed."""
    monkeypatch.setattr(config, "VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE", 1)
    monkeypatch.setattr(config, "VISIT_MINOR_MAX_DAYS_OUTSIDE", 4)
    monkeypatch.setitem(config.SEVERITY_BY_DEVIATION_TYPE, config.MISSING_DOCUMENTATION, config.MINOR)

    assert classify_severity(config.OUT_OF_WINDOW_VISIT, 2)[0] == config.MINOR
    assert classify_severity(config.OUT_OF_WINDOW_VISIT, 5)[0] == config.MAJOR
    assert classify_severity(config.MISSING_DOCUMENTATION)[0] == config.MINOR


def test_inconsistent_thresholds_are_rejected(monkeypatch):
    monkeypatch.setattr(config, "VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE", 7)
    monkeypatch.setattr(config, "VISIT_MINOR_MAX_DAYS_OUTSIDE", 3)
    with pytest.raises(SeverityRuleError, match="VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE"):
        check_severity_config()


def test_misspelled_severity_in_config_is_rejected(monkeypatch):
    monkeypatch.setitem(config.SEVERITY_BY_DEVIATION_TYPE, config.INCORRECT_DOSE, "Majr")
    with pytest.raises(SeverityRuleError, match="Majr"):
        check_severity_config()


def test_missing_type_in_config_is_rejected(monkeypatch):
    rules_without_dose = {k: v for k, v in config.SEVERITY_BY_DEVIATION_TYPE.items() if k != config.INCORRECT_DOSE}
    monkeypatch.setattr(config, "SEVERITY_BY_DEVIATION_TYPE", rules_without_dose)
    with pytest.raises(SeverityRuleError, match="Incorrect dose"):
        check_severity_config()


# ---------------------------------------------------------------------------
# Synthetic demo dataset
# ---------------------------------------------------------------------------
def test_every_demo_deviation_has_exactly_one_valid_severity(demo):
    assert len(demo) == 42
    assert demo["severity"].notna().all()
    assert set(demo["severity"]) <= set(config.SEVERITY_LEVELS)


def test_demo_severity_totals(demo):
    assert summarize_severity(demo)["by_severity"] == {
        config.MAJOR: 23,
        config.MINOR: 8,
        config.ADMINISTRATIVE: 11,
    }


def test_demo_site_104_severity(demo):
    by_site = summarize_severity(demo)["by_site"]
    assert by_site.loc["SITE-104"].to_dict() == {config.MAJOR: 12, config.MINOR: 0, config.ADMINISTRATIVE: 2}

    site = demo[demo["site_id"] == "SITE-104"]
    dosing_and_meds = site["deviation_type"].isin([config.INCORRECT_DOSE, config.PROHIBITED_MEDICATION])
    assert (site.loc[dosing_and_meds, "severity"] == config.MAJOR).all()


def test_demo_site_107_severity(demo):
    by_site = summarize_severity(demo)["by_site"]
    assert by_site.loc["SITE-107"].to_dict() == {config.MAJOR: 8, config.MINOR: 5, config.ADMINISTRATIVE: 2}

    site = demo[demo["site_id"] == "SITE-107"]
    severity_by_visit = site.groupby("visit")["severity"].apply(set).to_dict()
    assert severity_by_visit["Visit 2"] == {config.ADMINISTRATIVE}   # 1-2 days late
    assert severity_by_visit["Visit 3"] == {config.MINOR}            # 4-6 days outside
    assert config.MAJOR in severity_by_visit["Visit 4"]              # 8+ days late and missed


def test_demo_problem_sites_have_most_major_deviations(demo):
    majors = summarize_severity(demo)["by_site"][config.MAJOR].sort_values(ascending=False)
    assert list(majors.index[:2]) == ["SITE-104", "SITE-107"]
