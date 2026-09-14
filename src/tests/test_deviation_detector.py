"""
Phase 2 tests: protocol deviation detection.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v

Most tests build a tiny hand-made patient file so the expected result is
obvious. The last group runs the detector on the synthetic demo dataset.
"""

import io
import json

import pandas as pd
import pytest

import config
from core.deviation_detector import (
    DEVIATION_COLUMNS,
    days_outside_window,
    detect_deviations,
    run_detection,
    split_medications,
    visit_window,
)
from utils.data_loader import load_patients, load_protocol

COLUMNS = ["patient_id", "site_id", "visit", "actual_day", "dose_mg", "medication"]

# On-time days for the real protocol (day 0, 14, 28, 56)
ON_TIME_DAY = {"Visit 1": 0, "Visit 2": 14, "Visit 3": 28, "Visit 4": 56}


# ---------------------------------------------------------------------------
# Helpers for building small test datasets
# ---------------------------------------------------------------------------
def patient_rows(patient_id="PT-1", site_id="SITE-A", changes=None, skip_visits=()):
    """
    A fully compliant patient (all 4 visits, on time, 10 mg, no medication).
    `changes` edits specific visits, e.g. {"Visit 2": {"actual_day": 18}}.
    `skip_visits` leaves visits out entirely.
    """
    changes = changes or {}
    rows = []
    for visit, day in ON_TIME_DAY.items():
        if visit in skip_visits:
            continue
        row = {
            "patient_id": patient_id,
            "site_id": site_id,
            "visit": visit,
            "actual_day": day,
            "dose_mg": 10,
            "medication": "None",
        }
        row.update(changes.get(visit, {}))
        rows.append(row)
    return rows


def to_patients(rows):
    """Turn row dicts into a DataFrame via the real data loader (same types as the app)."""
    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(str(row[column]) for column in COLUMNS))
    return load_patients(io.StringIO("\n".join(lines) + "\n"))


@pytest.fixture(scope="module")
def protocol():
    return load_protocol()


@pytest.fixture(scope="module")
def demo_deviations():
    return run_detection()


def detect(rows, protocol):
    return detect_deviations(to_patients(rows), protocol)


def visit_2(protocol):
    return next(v for v in protocol["visits"] if v["visit"] == "Visit 2")


# ---------------------------------------------------------------------------
# Protocol loading and output shape
# ---------------------------------------------------------------------------
def test_detector_uses_the_protocol_file(protocol):
    assert protocol["expected_dose_mg"] == 10
    assert protocol["prohibited_medications"] == ["DrugB", "DrugC"]
    assert len(protocol["visits"]) == 4


def test_detector_reads_rules_from_protocol_not_hard_coded(tmp_path):
    """A different protocol gives different results for the same record."""
    custom = {
        "expected_dose_mg": 25,
        "visits": [{"visit": "Visit 1", "expected_day": 0, "window_days": 0}],
        "prohibited_medications": ["DrugX"],
    }
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(custom), encoding="utf-8")
    patients_csv = io.StringIO(
        ",".join(COLUMNS) + "\nPT-1,SITE-A,Visit 1,0,10,DrugB;DrugX\n"
    )

    deviations = run_detection(patients_csv, protocol_path)

    assert sorted(deviations["deviation_type"]) == [config.INCORRECT_DOSE, config.PROHIBITED_MEDICATION]
    assert "DrugX" in deviations.loc[deviations["deviation_type"] == config.PROHIBITED_MEDICATION, "explanation"].iloc[0]


def test_output_has_exactly_the_required_columns(protocol):
    deviations = detect(patient_rows(changes={"Visit 2": {"dose_mg": 20}}), protocol)
    assert list(deviations.columns) == DEVIATION_COLUMNS


def test_no_deviations_still_returns_table_with_columns(protocol):
    deviations = detect(patient_rows(), protocol)
    assert deviations.empty
    assert list(deviations.columns) == DEVIATION_COLUMNS


def test_every_detected_type_is_a_known_config_type(demo_deviations):
    assert set(demo_deviations["deviation_type"]) <= set(config.DEVIATION_TYPES)


# ---------------------------------------------------------------------------
# Compliant records
# ---------------------------------------------------------------------------
def test_compliant_patient_has_no_deviations(protocol):
    assert detect(patient_rows(), protocol).empty


def test_allowed_medication_is_not_a_deviation(protocol):
    rows = patient_rows(changes={"Visit 2": {"medication": "DrugA"}, "Visit 3": {"medication": "DrugA;DrugD"}})
    assert detect(rows, protocol).empty


def test_whole_number_dose_written_as_decimal_is_fine(protocol):
    assert detect(patient_rows(changes={"Visit 2": {"dose_mg": "10.0"}}), protocol).empty


# ---------------------------------------------------------------------------
# Visit windows (Visit 2: day 14, +/-2 -> allowed days 12 to 16)
# ---------------------------------------------------------------------------
def test_visit_window_is_calculated_from_protocol(protocol):
    assert visit_window(visit_2(protocol)) == (12, 16)


@pytest.mark.parametrize("day", [12, 13, 14, 15, 16])
def test_visit_inside_window_has_no_deviation(protocol, day):
    assert detect(patient_rows(changes={"Visit 2": {"actual_day": day}}), protocol).empty


@pytest.mark.parametrize(
    "day, expected_days_outside",
    [
        (11, 1),   # one day before the earliest allowed day
        (17, 1),   # one day after the latest allowed day
        (10, 2),
        (18, 2),
        (21, 5),
        (30, 14),
    ],
)
def test_visit_outside_window_records_days_outside(protocol, day, expected_days_outside):
    deviations = detect(patient_rows(changes={"Visit 2": {"actual_day": day}}), protocol)
    assert len(deviations) == 1
    row = deviations.iloc[0]
    assert row["deviation_type"] == config.OUT_OF_WINDOW_VISIT
    assert row["visit"] == "Visit 2"
    assert row["days_outside_window"] == expected_days_outside
    assert row["actual"] == f"Day {day}"
    assert row["expected"] == "Day 14 (allowed 12 to 16)"


def test_early_and_late_visits_are_explained_differently(protocol):
    early = detect(patient_rows(changes={"Visit 2": {"actual_day": 10}}), protocol).iloc[0]
    late = detect(patient_rows(changes={"Visit 2": {"actual_day": 18}}), protocol).iloc[0]
    assert "before the earliest allowed day (12)" in early["explanation"]
    assert "after the latest allowed day (16)" in late["explanation"]


@pytest.mark.parametrize("day, expected_days_outside", [(0, 0), (1, 1), (-1, 1)])
def test_zero_day_window_boundary(protocol, day, expected_days_outside):
    visit_1 = protocol["visits"][0]
    assert visit_1["window_days"] == 0
    assert days_outside_window(day, visit_1) == expected_days_outside


def test_visit_4_far_outside_window(protocol):
    # Visit 4: day 56 +/-5 -> latest allowed day 61; day 72 is 11 days outside
    deviations = detect(patient_rows(changes={"Visit 4": {"actual_day": 72}}), protocol)
    assert deviations.iloc[0]["days_outside_window"] == 11


def test_days_outside_window_is_blank_for_other_types(protocol):
    deviations = detect(patient_rows(changes={"Visit 2": {"dose_mg": 20}}), protocol)
    assert pd.isna(deviations.iloc[0]["days_outside_window"])


# ---------------------------------------------------------------------------
# Missed visits
# ---------------------------------------------------------------------------
def test_visit_with_no_record_is_missed(protocol):
    deviations = detect(patient_rows(skip_visits=["Visit 3"]), protocol)
    assert len(deviations) == 1
    row = deviations.iloc[0]
    assert row["deviation_type"] == config.MISSED_VISIT
    assert row["visit"] == "Visit 3"
    assert row["actual"] == "No record"
    assert row["site_id"] == "SITE-A"


def test_blank_actual_day_is_missed(protocol):
    rows = patient_rows(changes={"Visit 4": {"actual_day": "", "dose_mg": "", "medication": ""}})
    deviations = detect(rows, protocol)
    assert len(deviations) == 1  # no extra "missing documentation" for a visit that did not happen
    row = deviations.iloc[0]
    assert row["deviation_type"] == config.MISSED_VISIT
    assert row["actual"] == "Record has blank actual_day"


def test_several_missing_visits_for_one_patient(protocol):
    deviations = detect(patient_rows(skip_visits=["Visit 2", "Visit 3", "Visit 4"]), protocol)
    assert list(deviations["visit"]) == ["Visit 2", "Visit 3", "Visit 4"]
    assert set(deviations["deviation_type"]) == {config.MISSED_VISIT}


# ---------------------------------------------------------------------------
# Dosing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dose", [0, 5, 9.5, 15, 20])
def test_incorrect_dose_is_a_deviation(protocol, dose):
    deviations = detect(patient_rows(changes={"Visit 3": {"dose_mg": dose}}), protocol)
    assert len(deviations) == 1
    row = deviations.iloc[0]
    assert row["deviation_type"] == config.INCORRECT_DOSE
    assert row["expected"] == "10 mg"
    assert row["actual"] == f"{dose} mg"


def test_blank_dose_on_completed_visit_is_missing_documentation(protocol):
    deviations = detect(patient_rows(changes={"Visit 2": {"dose_mg": ""}}), protocol)
    assert list(deviations["deviation_type"]) == [config.MISSING_DOCUMENTATION]


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cell", ["DrugB", "DrugC", "DrugA;DrugB", "drugc", " DrugB "])
def test_prohibited_medication_is_a_deviation(protocol, cell):
    deviations = detect(patient_rows(changes={"Visit 2": {"medication": cell}}), protocol)
    assert list(deviations["deviation_type"]) == [config.PROHIBITED_MEDICATION]
    assert deviations.iloc[0]["actual"] == cell.strip()


def test_two_prohibited_medications_in_one_cell_are_two_deviations(protocol):
    deviations = detect(patient_rows(changes={"Visit 2": {"medication": "DrugB;DrugC"}}), protocol)
    assert len(deviations) == 2
    assert "DrugB" in deviations.iloc[0]["explanation"]
    assert "DrugC" in deviations.iloc[1]["explanation"]


def test_blank_medication_is_missing_documentation_but_none_is_fine(protocol):
    blank = detect(patient_rows(changes={"Visit 2": {"medication": ""}}), protocol)
    assert list(blank["deviation_type"]) == [config.MISSING_DOCUMENTATION]
    assert detect(patient_rows(changes={"Visit 2": {"medication": "none"}}), protocol).empty


def test_split_medications():
    assert split_medications("DrugA; DrugC") == ["DrugA", "DrugC"]
    assert split_medications("None") == []
    assert split_medications("DrugA;;") == ["DrugA"]


# ---------------------------------------------------------------------------
# Several deviations and several sites
# ---------------------------------------------------------------------------
def test_multiple_deviations_on_one_record(protocol):
    rows = patient_rows(changes={"Visit 3": {"actual_day": 40, "dose_mg": 20, "medication": "DrugC"}})
    deviations = detect(rows, protocol)
    assert len(deviations) == 3
    assert set(deviations["visit"]) == {"Visit 3"}
    assert list(deviations["deviation_type"]) == [
        config.OUT_OF_WINDOW_VISIT,
        config.INCORRECT_DOSE,
        config.PROHIBITED_MEDICATION,
    ]


def test_deviations_across_multiple_sites_keep_correct_site(protocol):
    rows = (
        patient_rows("PT-A1", "SITE-A", changes={"Visit 2": {"dose_mg": 20}})
        + patient_rows("PT-A2", "SITE-A")
        + patient_rows("PT-B1", "SITE-B", skip_visits=["Visit 4"])
        + patient_rows("PT-C1", "SITE-C", changes={"Visit 3": {"medication": "DrugB"}})
    )
    deviations = detect(rows, protocol)

    assert len(deviations) == 3
    by_patient = deviations.set_index("patient_id")
    assert by_patient.loc["PT-A1", "site_id"] == "SITE-A"
    assert by_patient.loc["PT-B1", "site_id"] == "SITE-B"
    assert by_patient.loc["PT-B1", "deviation_type"] == config.MISSED_VISIT
    assert by_patient.loc["PT-C1", "site_id"] == "SITE-C"
    assert "PT-A2" not in by_patient.index
    assert list(deviations["site_id"]) == ["SITE-A", "SITE-B", "SITE-C"]  # sorted by site


def test_record_with_unknown_visit_name_is_ignored(protocol):
    rows = patient_rows() + [{
        "patient_id": "PT-1", "site_id": "SITE-A", "visit": "Visit 99",
        "actual_day": 500, "dose_mg": 99, "medication": "DrugB",
    }]
    assert detect(rows, protocol).empty


# ---------------------------------------------------------------------------
# Synthetic demo dataset
# ---------------------------------------------------------------------------
def count(deviations, site_id, deviation_type=None):
    selected = deviations[deviations["site_id"] == site_id]
    if deviation_type:
        selected = selected[selected["deviation_type"] == deviation_type]
    return len(selected)


def test_demo_site_104_dosing_and_medication_problems_detected(demo_deviations):
    assert count(demo_deviations, "SITE-104", config.INCORRECT_DOSE) == 7
    assert count(demo_deviations, "SITE-104", config.PROHIBITED_MEDICATION) == 5

    site_104 = demo_deviations[demo_deviations["site_id"] == "SITE-104"]
    dose_patients = set(site_104.loc[site_104["deviation_type"] == config.INCORRECT_DOSE, "patient_id"])
    assert dose_patients == {"PT-104-02", "PT-104-04", "PT-104-05", "PT-104-07", "PT-104-09", "PT-104-11"}
    med_patients = set(site_104.loc[site_104["deviation_type"] == config.PROHIBITED_MEDICATION, "patient_id"])
    assert med_patients == {"PT-104-03", "PT-104-06", "PT-104-10", "PT-104-12"}


def test_demo_site_107_scheduling_problems_detected(demo_deviations):
    assert count(demo_deviations, "SITE-107", config.OUT_OF_WINDOW_VISIT) == 12
    assert count(demo_deviations, "SITE-107", config.MISSED_VISIT) == 3

    site_107 = demo_deviations[demo_deviations["site_id"] == "SITE-107"]
    missed = site_107[site_107["deviation_type"] == config.MISSED_VISIT].set_index("patient_id")
    assert missed.loc["PT-107-12", "actual"] == "No record"
    assert missed.loc["PT-107-02", "actual"] == "Record has blank actual_day"
    assert missed.loc["PT-107-11", "actual"] == "Record has blank actual_day"

    # Scheduling gets worse over time: more days outside the window at Visit 4
    window = site_107[site_107["deviation_type"] == config.OUT_OF_WINDOW_VISIT]
    mean_days = window.groupby("visit")["days_outside_window"].mean()
    assert mean_days["Visit 2"] < mean_days["Visit 3"] < mean_days["Visit 4"]


def test_demo_problem_sites_stand_out(demo_deviations):
    per_site = demo_deviations["site_id"].value_counts()
    other_sites = per_site.drop(["SITE-104", "SITE-107"])
    assert per_site["SITE-104"] > 2 * other_sites.max()
    assert per_site["SITE-107"] > 2 * other_sites.max()


def test_demo_clean_sites_have_no_deviations(demo_deviations):
    assert count(demo_deviations, "SITE-105") == 0
    assert count(demo_deviations, "SITE-110") == 0


def test_demo_total_deviation_count(demo_deviations):
    # The generator uses a fixed seed, so this number is stable.
    assert len(demo_deviations) == 42
