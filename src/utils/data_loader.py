"""
Load and validate TrialGuard input files.

This module only READS and CHECKS data. It does not look for protocol
deviations (that is core/deviation_detector.py, Phase 2).

Main functions
--------------
load_protocol(path)              -> dict
load_patients(source)            -> pandas DataFrame
get_data_warnings(patients, protocol) -> list of warning messages
summarize_patients(patients)     -> dict of simple counts

If a file cannot be used, a DataValidationError is raised with a message that
can be shown directly to the user.
"""

import json
from pathlib import Path

import pandas as pd

import config

# How many example row numbers to show in an error message
MAX_EXAMPLE_ROWS = 5


class DataValidationError(Exception):
    """An input file cannot be used. The message is written for the user."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
def load_protocol(path=config.PROTOCOL_PATH):
    """Read protocol.json and check it has everything TrialGuard needs."""
    path = Path(path)
    if not path.exists():
        raise DataValidationError(f"Protocol file not found: {path}")

    try:
        protocol = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DataValidationError(
            f"Protocol file is not valid JSON (line {error.lineno}): {error.msg}"
        ) from error

    problems = _find_protocol_problems(protocol)
    if problems:
        raise DataValidationError(
            "The protocol file has problems:\n- " + "\n- ".join(problems)
        )
    return protocol


def _is_number(value):
    # bool is a subclass of int in Python, so exclude it explicitly
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _find_protocol_problems(protocol):
    if not isinstance(protocol, dict):
        return ["the file must contain a JSON object { ... }"]

    problems = []

    if not _is_number(protocol.get("expected_dose_mg")):
        problems.append("'expected_dose_mg' must be a number")

    prohibited = protocol.get("prohibited_medications")
    if not isinstance(prohibited, list) or not all(isinstance(m, str) for m in prohibited):
        problems.append("'prohibited_medications' must be a list of medication names")

    visits = protocol.get("visits")
    if not isinstance(visits, list) or len(visits) == 0:
        problems.append("'visits' must be a non-empty list")
        return problems

    seen_names = set()
    for number, visit in enumerate(visits, start=1):
        if not isinstance(visit, dict):
            problems.append(f"visit #{number} must be an object")
            continue
        name = visit.get("visit")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"visit #{number} needs a 'visit' name")
        elif name in seen_names:
            problems.append(f"visit name '{name}' appears more than once")
        else:
            seen_names.add(name)
        if not _is_number(visit.get("expected_day")):
            problems.append(f"visit #{number} needs a numeric 'expected_day'")
        window = visit.get("window_days")
        if not _is_number(window) or window < 0:
            problems.append(f"visit #{number} needs a 'window_days' of 0 or more")

    return problems


# ---------------------------------------------------------------------------
# Patient records
# ---------------------------------------------------------------------------
def load_patients(source=config.DEMO_PATIENTS_PATH):
    """
    Read patient visit records from a CSV file and validate them.

    `source` can be a file path or an uploaded file object (for example, the
    object Streamlit's file uploader returns).

    Returns a DataFrame where:
      - column names are lower-case with spaces removed
      - text values have extra spaces removed
      - actual_day and dose_mg are numbers (blank cells become NaN)
      - medication is text; "None" stays as the word "None"
    """
    try:
        # dtype=str + keep_default_na=False: read every cell as plain text.
        # Without this, pandas would silently turn the word "None" into a
        # missing value, and we could no longer tell "no medication" apart
        # from "medication not documented".
        patients = pd.read_csv(source, dtype=str, keep_default_na=False)
    except FileNotFoundError as error:
        raise DataValidationError(f"Patient file not found: {source}") from error
    except pd.errors.EmptyDataError as error:
        raise DataValidationError("The patient file is empty.") from error
    except pd.errors.ParserError as error:
        raise DataValidationError(
            f"The patient file could not be read as a CSV file: {error}"
        ) from error
    except UnicodeDecodeError as error:
        raise DataValidationError(
            "The patient file could not be read. Please save it as a UTF-8 CSV file."
        ) from error

    # Tidy column names: " Patient_ID " -> "patient_id"
    patients.columns = [str(column).strip().lower() for column in patients.columns]

    missing_columns = [c for c in config.REQUIRED_COLUMNS if c not in patients.columns]
    if missing_columns:
        raise DataValidationError(
            "The patient file is missing required column(s): "
            + ", ".join(missing_columns)
            + ".\nColumns found: "
            + ", ".join(patients.columns)
            + ".\nRequired columns: "
            + ", ".join(config.REQUIRED_COLUMNS)
            + "."
        )

    if patients.empty:
        raise DataValidationError("The patient file has column headers but no records.")

    # Remove leading/trailing spaces from every text cell
    for column in patients.columns:
        patients[column] = patients[column].str.strip()

    # Identifier columns must never be blank
    for column in ("patient_id", "site_id", "visit"):
        blank = patients[column] == ""
        if blank.any():
            raise DataValidationError(
                f"Column '{column}' is blank in row(s) {_example_rows(blank)}. "
                "Every record needs a patient_id, site_id and visit."
            )

    # Numeric columns: blank is allowed (e.g. a missed visit), text is not
    for column in config.NUMERIC_COLUMNS:
        converted = pd.to_numeric(patients[column], errors="coerce")
        not_a_number = converted.isna() & (patients[column] != "")
        if not_a_number.any():
            examples = patients.loc[not_a_number, column].head(MAX_EXAMPLE_ROWS).tolist()
            raise DataValidationError(
                f"Column '{column}' must contain numbers, but row(s) "
                f"{_example_rows(not_a_number)} contain {examples}."
            )
        patients[column] = converted

    return patients


def _example_rows(mask):
    """
    Turn a True/False column into readable CSV row numbers.
    Row 1 is the header, so the first record is row 2.
    """
    row_numbers = [str(position + 2) for position, flagged in enumerate(mask.tolist()) if flagged]
    text = ", ".join(row_numbers[:MAX_EXAMPLE_ROWS])
    if len(row_numbers) > MAX_EXAMPLE_ROWS:
        text += f" (and {len(row_numbers) - MAX_EXAMPLE_ROWS} more)"
    return text


def get_data_warnings(patients, protocol):
    """
    Find things that look wrong but do not stop the analysis.
    Returns a list of plain-English messages (empty list = no warnings).
    """
    warnings = []

    known_visits = {visit["visit"] for visit in protocol["visits"]}
    unknown_visits = sorted(set(patients["visit"]) - known_visits)
    if unknown_visits:
        warnings.append(
            "Visit name(s) not in the protocol will be ignored: "
            + ", ".join(unknown_visits)
        )

    duplicates = patients.duplicated(subset=["patient_id", "visit"], keep=False)
    if duplicates.any():
        count = patients.loc[duplicates, ["patient_id", "visit"]].drop_duplicates().shape[0]
        warnings.append(
            f"{count} patient/visit combination(s) appear more than once "
            f"(rows {_example_rows(duplicates)})."
        )

    sites_per_patient = patients.groupby("patient_id")["site_id"].nunique()
    multi_site_patients = sites_per_patient[sites_per_patient > 1].index.tolist()
    if multi_site_patients:
        warnings.append(
            "Patient(s) recorded at more than one site: "
            + ", ".join(multi_site_patients[:MAX_EXAMPLE_ROWS])
        )

    for column in config.NUMERIC_COLUMNS:
        negative = patients[column] < 0
        if negative.any():
            warnings.append(
                f"Column '{column}' has negative values in row(s) {_example_rows(negative)}."
            )

    return warnings


def summarize_patients(patients):
    """Simple counts used for a quick check of a dataset."""
    visits_per_patient = patients.groupby("patient_id")["visit"].count()
    return {
        "total_records": len(patients),
        "total_patients": patients["patient_id"].nunique(),
        "total_sites": patients["site_id"].nunique(),
        "patients_per_site": patients.groupby("site_id")["patient_id"].nunique().to_dict(),
        "min_visits_per_patient": int(visits_per_patient.min()),
        "max_visits_per_patient": int(visits_per_patient.max()),
        "missed_visit_records": int(patients["actual_day"].isna().sum()),
    }
