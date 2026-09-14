"""
Protocol deviation detection.

Compares every patient visit record against the protocol and returns one row
per deviation found. Every rule is plain Python so it can be read and checked.

This module only DETECTS deviations. It does not decide how serious they are
(that is Phase 3: core/severity.py) and it does not score sites (Phase 4).

Rules
-----
1. Missed visit
   - The record exists but actual_day is blank, or
   - the protocol expects a visit but the patient has no record for it.
     Whether an unrecorded visit counts depends on `assume_schedule_complete`:
       True  (default, used by the demo data): every patient has finished the
             schedule, so EVERY unrecorded visit is missed.
       False (trial still ongoing): an unrecorded visit is missed only if the
             patient has a record for a LATER visit. Visits after the
             patient's last record are "not yet due" and are not flagged.
             Trade-off: a patient who dropped out is not flagged for the visits
             they never reached - add a row with a blank actual_day for those.
2. Out-of-window visit
   - actual_day is earlier than (expected_day - window_days) or later than
     (expected_day + window_days). The number of days outside is recorded.
3. Incorrect dose
   - dose_mg is different from the protocol's expected_dose_mg.
4. Prohibited medication
   - A medication in the medication cell is on the protocol's prohibited list.
     Matching ignores upper/lower case. Several medications can be listed in
     one cell separated by ";" — each prohibited one is its own deviation.
5. Missing documentation
   - A visit that happened has a blank dose_mg or a blank medication cell.
     ("None" means no other medication and is NOT a deviation.)

A missed visit is not checked for rules 2-5, because the visit did not happen.
Records whose visit name is not in the protocol are skipped. (The dashboard
removes them beforehand with data_loader.prepare_patient_records() and tells
the user.)

PROTOTYPE NOTICE: simplified hackathon rules on synthetic data. Not a
regulatory determination and not for real clinical decisions.
"""

import pandas as pd

import config
from utils.data_loader import load_patients, load_protocol

# Columns of the deviations table, in display order
DEVIATION_COLUMNS = [
    "patient_id",
    "site_id",
    "visit",
    "deviation_type",
    "expected",
    "actual",
    "explanation",
    "days_outside_window",  # only filled for out-of-window visits
]


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------
def run_detection(patients_source=config.DEMO_PATIENTS_PATH, protocol_path=config.PROTOCOL_PATH):
    """Load the protocol and patient records from files, then detect deviations."""
    protocol = load_protocol(protocol_path)
    patients = load_patients(patients_source)
    return detect_deviations(patients, protocol)


def detect_deviations(patients, protocol, assume_schedule_complete=True):
    """
    Compare patient records (a DataFrame from load_patients) with the protocol.
    Returns a DataFrame with one row per deviation, using DEVIATION_COLUMNS.
    See rule 1 above for `assume_schedule_complete`.
    """
    visits_by_name = {visit["visit"]: visit for visit in protocol["visits"]}
    deviations = []

    # Rules 1-5 for every record that exists
    for record in patients.to_dict("records"):
        visit = visits_by_name.get(record["visit"])
        if visit is None:
            continue  # visit name not in the protocol
        deviations.extend(check_visit_record(record, visit, protocol))

    # Rule 1 for visits with no record at all
    deviations.extend(find_missing_visit_records(patients, protocol, assume_schedule_complete))

    return _to_sorted_table(deviations, protocol)


# ---------------------------------------------------------------------------
# Visit windows
# ---------------------------------------------------------------------------
def visit_window(visit):
    """Return (earliest_allowed_day, latest_allowed_day) for a protocol visit."""
    earliest = visit["expected_day"] - visit["window_days"]
    latest = visit["expected_day"] + visit["window_days"]
    return earliest, latest


def days_outside_window(actual_day, visit):
    """0 if the day is inside the window, otherwise how many days outside it is."""
    earliest, latest = visit_window(visit)
    if actual_day < earliest:
        return earliest - actual_day
    if actual_day > latest:
        return actual_day - latest
    return 0


# ---------------------------------------------------------------------------
# Checks for one record
# ---------------------------------------------------------------------------
def check_visit_record(record, visit, protocol):
    """Apply every rule to one visit record. Returns a list of deviation dicts."""
    if pd.isna(record["actual_day"]):
        return [_missed_visit_with_blank_day(record, visit)]

    deviations = []
    deviations.extend(_check_visit_timing(record, visit))
    deviations.extend(_check_dose(record, protocol))
    deviations.extend(_check_medication(record, protocol))
    return deviations


def _missed_visit_with_blank_day(record, visit):
    return _deviation(
        record,
        config.MISSED_VISIT,
        expected=_describe_window(visit),
        actual="Record has blank actual_day",
        explanation=(
            f"{record['visit']} has a record but no actual_day, "
            "so the visit is treated as missed."
        ),
    )


def _check_visit_timing(record, visit):
    actual_day = record["actual_day"]
    outside = days_outside_window(actual_day, visit)
    if outside == 0:
        return []

    earliest, latest = visit_window(visit)
    if actual_day > latest:
        where = f"after the latest allowed day ({_format_number(latest)})"
    else:
        where = f"before the earliest allowed day ({_format_number(earliest)})"

    return [_deviation(
        record,
        config.OUT_OF_WINDOW_VISIT,
        expected=_describe_window(visit),
        actual=f"Day {_format_number(actual_day)}",
        explanation=(
            f"{record['visit']} happened on day {_format_number(actual_day)}, "
            f"{_format_number(outside)} day(s) {where}."
        ),
        days_outside=outside,
    )]


def _check_dose(record, protocol):
    expected_dose = protocol["expected_dose_mg"]
    dose = record["dose_mg"]

    if pd.isna(dose):
        return [_deviation(
            record,
            config.MISSING_DOCUMENTATION,
            expected=f"{_format_number(expected_dose)} mg recorded",
            actual="dose_mg is blank",
            explanation=f"No dose was recorded for {record['visit']}, which took place.",
        )]

    if dose != expected_dose:
        return [_deviation(
            record,
            config.INCORRECT_DOSE,
            expected=f"{_format_number(expected_dose)} mg",
            actual=f"{_format_number(dose)} mg",
            explanation=(
                f"Dose recorded as {_format_number(dose)} mg; "
                f"the protocol requires {_format_number(expected_dose)} mg."
            ),
        )]

    return []


def _check_medication(record, protocol):
    cell = record["medication"]

    if cell == "":
        return [_deviation(
            record,
            config.MISSING_DOCUMENTATION,
            expected=f"Medication recorded (or '{config.NO_MEDICATION_VALUE}')",
            actual="medication is blank",
            explanation=(
                f"The medication field is blank for {record['visit']}. "
                f"Use '{config.NO_MEDICATION_VALUE}' if the patient takes no other medication."
            ),
        )]

    prohibited_by_lower_name = {name.lower(): name for name in protocol["prohibited_medications"]}
    deviations = []
    for medication in split_medications(cell):
        protocol_name = prohibited_by_lower_name.get(medication.lower())
        if protocol_name is None:
            continue
        deviations.append(_deviation(
            record,
            config.PROHIBITED_MEDICATION,
            expected="None of: " + ", ".join(protocol["prohibited_medications"]),
            actual=cell,
            explanation=f"{protocol_name} is on the protocol's prohibited medication list.",
        ))
    return deviations


def split_medications(cell):
    """'DrugA; DrugC' -> ['DrugA', 'DrugC']. 'None' and blanks are dropped."""
    names = [part.strip() for part in cell.split(config.MEDICATION_SEPARATOR)]
    return [name for name in names if name and name.lower() != config.NO_MEDICATION_VALUE.lower()]


# ---------------------------------------------------------------------------
# Visits with no record at all
# ---------------------------------------------------------------------------
def find_missing_visit_records(patients, protocol, assume_schedule_complete=True):
    """
    Flag protocol visits that a patient has no record for.
    With assume_schedule_complete=False, visits after the patient's last
    recorded visit are skipped (not yet due) - see rule 1 at the top.
    """
    deviations = []
    for record, visit, after_last_record in unrecorded_visits(patients, protocol):
        if after_last_record and not assume_schedule_complete:
            continue
        deviations.append(_deviation(
            record,
            config.MISSED_VISIT,
            expected=_describe_window(visit),
            actual="No record",
            explanation=(
                f"No record exists for {visit['visit']} "
                f"(expected around day {_format_number(visit['expected_day'])})."
            ),
        ))
    return deviations


def count_visits_not_yet_due(patients, protocol):
    """How many unrecorded visits come after each patient's last recorded visit."""
    return sum(1 for _, _, after_last_record in unrecorded_visits(patients, protocol) if after_last_record)


def unrecorded_visits(patients, protocol):
    """
    Yield (record, visit, after_last_record) for every protocol visit a patient
    has no record for. after_last_record is True when the patient has no record
    for this visit or any later visit in the schedule.
    """
    if patients.empty:
        return

    site_by_patient = patients.groupby("patient_id")["site_id"].first()
    recorded_visits = patients.groupby("patient_id")["visit"].apply(set)
    schedule = protocol["visits"]

    for patient_id, site_id in site_by_patient.items():
        recorded = recorded_visits[patient_id]
        positions = [number for number, visit in enumerate(schedule) if visit["visit"] in recorded]
        last_recorded_position = max(positions) if positions else -1

        for number, visit in enumerate(schedule):
            if visit["visit"] in recorded:
                continue
            record = {"patient_id": patient_id, "site_id": site_id, "visit": visit["visit"]}
            yield record, visit, number > last_recorded_position


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _deviation(record, deviation_type, expected, actual, explanation, days_outside=None):
    return {
        "patient_id": record["patient_id"],
        "site_id": record["site_id"],
        "visit": record["visit"],
        "deviation_type": deviation_type,
        "expected": expected,
        "actual": actual,
        "explanation": explanation,
        "days_outside_window": days_outside,
    }


def _describe_window(visit):
    earliest, latest = visit_window(visit)
    return (
        f"Day {_format_number(visit['expected_day'])} "
        f"(allowed {_format_number(earliest)} to {_format_number(latest)})"
    )


def _format_number(value):
    """20.0 -> '20', 7.5 -> '7.5'"""
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _to_sorted_table(deviations, protocol):
    """Build the deviations DataFrame, sorted by site, patient, visit order, type."""
    table = pd.DataFrame(deviations, columns=DEVIATION_COLUMNS)
    if table.empty:
        table["days_outside_window"] = table["days_outside_window"].astype("Int64")
        return table

    visit_order = {visit["visit"]: number for number, visit in enumerate(protocol["visits"])}
    type_order = {name: number for number, name in enumerate(config.DEVIATION_TYPES)}
    table = (
        table.assign(
            _visit_order=table["visit"].map(visit_order),
            _type_order=table["deviation_type"].map(type_order),
        )
        .sort_values(["site_id", "patient_id", "_visit_order", "_type_order"], kind="stable")
        .drop(columns=["_visit_order", "_type_order"])
        .reset_index(drop=True)
    )

    # Show whole days as 2 rather than 2.0 (blank for non-window deviations)
    days = pd.to_numeric(table["days_outside_window"])
    if (days.dropna() % 1 == 0).all():
        days = days.astype("Int64")
    table["days_outside_window"] = days
    return table


def summarize_deviations(deviations):
    """Simple counts for a quick check of the detection results."""
    return {
        "total_deviations": len(deviations),
        "by_type": deviations["deviation_type"].value_counts().to_dict(),
        "by_site": deviations["site_id"].value_counts().sort_index().to_dict(),
        "patients_affected": deviations["patient_id"].nunique(),
    }
