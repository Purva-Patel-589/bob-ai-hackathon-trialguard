"""
Data preparation for the Streamlit dashboard.

This module connects the existing TrialGuard steps and reshapes their results
into tables the dashboard can show. It contains NO detection, severity,
scoring or warning rules of its own - it only calls the core modules:

    data_loader -> deviation_detector -> severity -> risk_scoring -> early_warning

It does not import Streamlit, so every function can be tested with pytest.
"""

import io

import pandas as pd

import config
from core.deviation_detector import count_visits_not_yet_due, detect_deviations
from core.early_warning import detect_early_warnings, summarize_site_warnings
from core.risk_scoring import (
    FACTOR_BY_DEVIATION_TYPE,
    FACTOR_POINT_COLUMNS,
    FACTOR_REPEATED_PATTERNS,
    RiskScoringError,
    calculate_site_risk,
    top_risk_factors,
)
from core.severity import SeverityRuleError, add_severity
from utils.data_loader import (
    DataValidationError,
    get_data_warnings,
    load_patients,
    load_protocol,
    prepare_patient_records,
)

ALL_SITES = "All Sites"

LEVEL_ICONS = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟢"}

# Errors whose message is already written for the user
KNOWN_ERRORS = (DataValidationError, SeverityRuleError, RiskScoringError)


# ---------------------------------------------------------------------------
# Running the analysis
# ---------------------------------------------------------------------------
def run_analysis(patients, protocol, assume_schedule_complete=True):
    """
    Run every TrialGuard step on already-loaded patient records.

    assume_schedule_complete: True if every patient has finished the visit
    schedule (the demo data); False for a trial that is still ongoing, so
    visits after a patient's last record are not counted as missed.

    Returns a dict with: protocol, patients, data_notes, data_warnings,
    assume_schedule_complete, visits_not_yet_due, deviations, site_risk,
    warnings, site_summary.
    """
    prepared, notes = prepare_patient_records(patients, protocol)
    deviations = add_severity(detect_deviations(prepared, protocol, assume_schedule_complete))
    site_risk = calculate_site_risk(deviations, prepared)
    warnings = detect_early_warnings(site_risk, deviations, protocol)
    return {
        "protocol": protocol,
        "patients": prepared,
        "data_notes": notes,
        "data_warnings": get_data_warnings(prepared, protocol),
        "assume_schedule_complete": assume_schedule_complete,
        "visits_not_yet_due": 0 if assume_schedule_complete else count_visits_not_yet_due(prepared, protocol),
        "deviations": deviations,
        "site_risk": site_risk,
        "warnings": warnings,
        "site_summary": summarize_site_warnings(site_risk, warnings),
    }


def analyze_source(source, protocol_path=config.PROTOCOL_PATH, assume_schedule_complete=True):
    """
    Load patient records from a file path or file-like object and analyse them.

    Never raises. Returns (result, error_message):
      - success: (result dict, None)
      - failure: (None, message the dashboard can show to the user)
    """
    try:
        protocol = load_protocol(protocol_path)
        patients = load_patients(source)
        return run_analysis(patients, protocol, assume_schedule_complete), None
    except KNOWN_ERRORS as error:
        return None, str(error)
    except Exception as error:  # noqa: BLE001 - the dashboard must never show a traceback
        return None, (
            "TrialGuard could not analyse this file because of an unexpected problem "
            f"({type(error).__name__}: {error}). Please check the file format and try again."
        )


def protocol_visit_names(protocol_path=config.PROTOCOL_PATH):
    """Visit names from the protocol for help text; empty list if the protocol can't be read."""
    try:
        return [visit["visit"] for visit in load_protocol(protocol_path)["visits"]]
    except DataValidationError:
        return []


def analyze_uploaded_bytes(file_bytes, assume_schedule_complete=True):
    """Analyse the bytes of an uploaded CSV file. Same return value as analyze_source()."""
    if not file_bytes:
        return None, "The uploaded file is empty."
    return analyze_source(io.BytesIO(file_bytes), assume_schedule_complete=assume_schedule_complete)


# ---------------------------------------------------------------------------
# Study overview
# ---------------------------------------------------------------------------
def study_metrics(result):
    """Headline numbers for the metric cards."""
    site_risk = result["site_risk"]
    levels = site_risk["risk_level"].value_counts()
    return {
        "total_sites": len(site_risk),
        "total_patients": int(result["patients"]["patient_id"].nunique()),
        "total_deviations": len(result["deviations"]),
        "high_risk_sites": int(levels.get("HIGH", 0)),
        "medium_risk_sites": int(levels.get("MEDIUM", 0)),
        "low_risk_sites": int(levels.get("LOW", 0)),
        "sites_with_warnings": int(result["warnings"]["site_id"].nunique()),
    }


def level_label(level):
    """'HIGH' -> '🔴 HIGH' (icon + word, so colour is never the only signal)."""
    return f"{LEVEL_ICONS.get(level, '⚪')} {level}"


def site_overview_table(site_risk, site_summary=None):
    """
    The site risk table with friendly column names, highest risk first.
    If `site_summary` (from summarize_site_warnings) is given, an
    'Early Warnings' count column is added.
    """
    table = site_risk.sort_values("risk_score", ascending=False, kind="stable")
    overview = pd.DataFrame({
        "Site": table["site_id"],
        "Risk Level": table["risk_level"].map(level_label),
        "Risk Score": table["risk_score"],
        "Patients": table["patients"],
        "Deviations": table["total_deviations"],
        "Major": table["major_deviations"],
        "Minor": table["minor_deviations"],
        "Administrative": table["administrative_deviations"],
    })
    if site_summary is not None:
        warning_counts = site_summary.set_index("site_id")["warning_count"]
        overview["Early Warnings"] = table["site_id"].map(warning_counts).fillna(0).astype(int)
    return overview.reset_index(drop=True)


def count_by(deviations, column, order):
    """Count deviations by a column, keeping every value in `order` (zeros included)."""
    counts = deviations[column].value_counts()
    return pd.DataFrame({column: order, "count": [int(counts.get(value, 0)) for value in order]})


def site_options(site_risk):
    """Choices for the site selector: 'All Sites' then sites from highest to lowest risk."""
    return [ALL_SITES] + site_risk["site_id"].tolist()


# ---------------------------------------------------------------------------
# One site
# ---------------------------------------------------------------------------
def site_details(result, site_id):
    """Everything the dashboard shows for one site."""
    site_risk = result["site_risk"].set_index("site_id")
    if site_id not in site_risk.index:
        raise KeyError(f"Unknown site: {site_id}")

    row = site_risk.loc[site_id].to_dict()
    row["site_id"] = site_id
    deviations = result["deviations"]
    site_deviations = deviations[deviations["site_id"] == site_id]
    summary = result["site_summary"].set_index("site_id").loc[site_id]

    return {
        "row": row,
        "headline": summary["headline"],
        "warnings": result["warnings"][result["warnings"]["site_id"] == site_id].reset_index(drop=True),
        "top_factors": top_risk_factors(row),
        "affected_patients": int(site_deviations["patient_id"].nunique()),
        "breakdown": deviation_breakdown(site_deviations, row),
        "records": deviation_records(site_deviations),
        "deviations": site_deviations.reset_index(drop=True),  # raw rows, for the CAPA generator
    }


def deviation_breakdown(site_deviations, site_row):
    """
    What is causing a site's risk: for each risk factor, how many deviations
    and how many risk points. Points come straight from the Phase 4 scoring.
    """
    factor_of_each = site_deviations["deviation_type"].map(FACTOR_BY_DEVIATION_TYPE)
    counts = factor_of_each.value_counts()
    rows = []
    for factor, column in FACTOR_POINT_COLUMNS.items():
        rows.append({
            "Risk factor": factor,
            "Deviations": None if factor == FACTOR_REPEATED_PATTERNS else int(counts.get(factor, 0)),
            "Risk points": int(site_row[column]),
        })
    breakdown = pd.DataFrame(rows)
    breakdown["Deviations"] = breakdown["Deviations"].astype("Int64")
    return breakdown


RECORD_COLUMNS = {
    "patient_id": "Patient",
    "visit": "Visit",
    "deviation_type": "Deviation type",
    "severity": "Severity",
    "expected": "Expected",
    "actual": "Actual",
    "days_outside_window": "Days outside window",
    "explanation": "Explanation",
    "severity_rule": "Why this severity",
}


def deviation_records(site_deviations):
    """A site's deviations with readable column names, most severe first."""
    severity_order = {level: number for number, level in enumerate(config.SEVERITY_LEVELS)}
    ordered = site_deviations.assign(_order=site_deviations["severity"].map(severity_order))
    ordered = ordered.sort_values(["_order", "patient_id"], kind="stable")
    return ordered[list(RECORD_COLUMNS)].rename(columns=RECORD_COLUMNS).reset_index(drop=True)


def filter_records(records, severities=None, deviation_types=None):
    """Keep only rows matching the chosen severities and deviation types (None = keep all)."""
    keep = pd.Series(True, index=records.index)
    if severities:
        keep &= records["Severity"].isin(severities)
    if deviation_types:
        keep &= records["Deviation type"].isin(deviation_types)
    return records[keep].reset_index(drop=True)
