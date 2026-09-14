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
import warnings as python_warnings  # renamed: get_data_warnings() has its own 'warnings' list
from pathlib import Path

import pandas as pd

import config

# How many example row numbers to show in an error message
MAX_EXAMPLE_ROWS = 5

# Medication values that probably mean "no medication" but are not the word
# config.NO_MEDICATION_VALUE ("None"). They are still treated as medication
# names, but the user gets a warning.
NO_MEDICATION_LOOKALIKES = {"na", "n/a", "-", "--", "null", "nil", "nan", "no", "nothing", "0"}


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
    patients = _read_csv_as_text(source)

    # Tidy column names: " Patient_ID " -> "patient_id"
    patients.columns = [str(column).strip().lower() for column in patients.columns]

    missing_columns = [c for c in config.REQUIRED_COLUMNS if c not in patients.columns]
    if missing_columns:
        message = (
            "The patient file is missing required column(s): "
            + ", ".join(missing_columns)
            + ".\nColumns found: "
            + ", ".join(patients.columns)
            + ".\nRequired columns: "
            + ", ".join(config.REQUIRED_COLUMNS)
            + "."
        )
        if len(patients.columns) == 1 and (";" in patients.columns[0] or "\t" in patients.columns[0]):
            message += (
                "\nTip: this file seems to use semicolons or tabs between values. "
                "Save it as a comma-separated CSV and upload it again."
            )
        raise DataValidationError(message)

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


def _read_csv_as_text(source):
    """
    Read the CSV with every cell as plain text.

    Tries UTF-8 first (this also handles the invisible marker Excel adds to
    "CSV UTF-8" files), then Windows-1252, the default for Excel's plain
    "CSV (Comma delimited)" on Windows.
    """
    try:
        return _read_csv_with_encoding(source, "utf-8-sig")
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)  # an uploaded file must be rewound before reading it again
        try:
            return _read_csv_with_encoding(source, "cp1252")
        except UnicodeDecodeError as error:
            raise DataValidationError(
                "The patient file could not be read. Please save it as a UTF-8 CSV file."
            ) from error


def _read_csv_with_encoding(source, encoding):
    try:
        with python_warnings.catch_warnings():
            # pandas only *warns* when the first record has more values than
            # the header; treat that as an error instead of silently dropping data
            python_warnings.simplefilter("error", pd.errors.ParserWarning)
            # dtype=str + keep_default_na=False: read every cell as plain text.
            # Without this, pandas would silently turn the word "None" into a
            # missing value, and we could no longer tell "no medication" apart
            # from "medication not documented".
            # index_col=False: never use the first column as row labels.
            return pd.read_csv(source, dtype=str, keep_default_na=False, index_col=False, encoding=encoding)
    except FileNotFoundError as error:
        raise DataValidationError(f"Patient file not found: {source}") from error
    except pd.errors.EmptyDataError as error:
        raise DataValidationError("The patient file is empty.") from error
    except (pd.errors.ParserError, pd.errors.ParserWarning) as error:
        raise DataValidationError(
            "The patient file could not be read as a CSV table: some rows have more values "
            "than there are column headers. Check for extra commas (text that contains a "
            f"comma must be in quotes). Details: {str(error).strip()}"
        ) from error


def _example_rows(mask):
    """
    Turn a True/False column into readable CSV row numbers.
    Row 1 is the header, so the record with row label 0 is row 2. Row labels
    are kept when records are removed, so the numbers still match the file.
    """
    row_numbers = [str(label + 2) for label in mask[mask].index]
    text = ", ".join(row_numbers[:MAX_EXAMPLE_ROWS])
    if len(row_numbers) > MAX_EXAMPLE_ROWS:
        text += f" (and {len(row_numbers) - MAX_EXAMPLE_ROWS} more)"
    return text


def prepare_patient_records(patients, protocol):
    """
    Get validated records ready for analysis. Returns (prepared_records, notes).

    - Visit names are matched to the protocol ignoring capitals and extra
      spaces ("visit  2" -> "Visit 2").
    - Records whose visit name is not in the protocol are left out, because
      they cannot be compared with the schedule.
    - Exact duplicate records (every column identical) are kept only once.

    `notes` lists every change in plain English. Row labels are kept so
    warnings still point at the right CSV rows. Raises DataValidationError if
    no records are left.
    """
    if patients.empty:
        raise DataValidationError("The patient file has no records to analyse.")

    notes = []
    protocol_names = [visit["visit"] for visit in protocol["visits"]]
    name_by_key = {_visit_key(name): name for name in protocol_names}

    matched_names = patients["visit"].map(lambda name: name_by_key.get(_visit_key(name)))
    unknown = matched_names.isna()

    renamed = ~unknown & (matched_names != patients["visit"])
    if renamed.any():
        examples = patients.loc[renamed, "visit"].drop_duplicates().head(3).tolist()
        notes.append(
            f"Matched {int(renamed.sum())} visit name(s) to the protocol ignoring capitals and spaces "
            f"(for example '{examples[0]}' was read as '{name_by_key[_visit_key(examples[0])]}')."
        )

    if unknown.all():
        found = ", ".join(sorted(patients["visit"].unique())[:MAX_EXAMPLE_ROWS])
        raise DataValidationError(
            "None of the records can be analysed because no visit name matches the protocol.\n"
            f"Visit names found: {found}.\n"
            f"Protocol visit names: {', '.join(protocol_names)}."
        )
    if unknown.any():
        ignored = ", ".join(sorted(patients.loc[unknown, "visit"].unique())[:MAX_EXAMPLE_ROWS])
        notes.append(
            f"Ignored {int(unknown.sum())} record(s) whose visit name is not in the protocol "
            f"({ignored}; rows {_example_rows(unknown)}). Protocol visit names: {', '.join(protocol_names)}."
        )

    prepared = patients.assign(visit=matched_names)[~unknown]

    exact_duplicates = prepared.duplicated(subset=config.REQUIRED_COLUMNS, keep="first")
    if exact_duplicates.any():
        notes.append(
            f"Removed {int(exact_duplicates.sum())} exact duplicate record(s) "
            f"(rows {_example_rows(exact_duplicates)}); each record is counted once."
        )
        prepared = prepared[~exact_duplicates]

    return prepared, notes


def _visit_key(name):
    """'  visit   2 ' -> 'visit 2' (for matching visit names)."""
    return " ".join(str(name).split()).lower()


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
            f"{count} patient/visit combination(s) appear more than once with different values "
            f"(rows {_example_rows(duplicates)}). Each record is checked separately."
        )

    lookalikes = patients["medication"].str.lower().isin(NO_MEDICATION_LOOKALIKES)
    if lookalikes.any():
        values = ", ".join(f"'{value}'" for value in patients.loc[lookalikes, "medication"].unique())
        warnings.append(
            f"Medication value(s) {values} in row(s) {_example_rows(lookalikes)} look like "
            f"'no medication'. Only '{config.NO_MEDICATION_VALUE}' means no medication; other text "
            "is treated as a medication name."
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
