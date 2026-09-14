"""
Site-level risk scoring.

Turns the classified deviations (from core/severity.py) into one 0-100 risk
score per site. Every weight comes from config.py and the formula is written
out step by step below.

Formula
-------
1. Points for each deviation
       severity points      Major 10, Minor 4, Administrative 1
     + type bonus           Incorrect dose +5, Prohibited medication +7,
                            Missed visit +3, Out-of-window visit +3
2. Repeated-pattern bonus
       +5 for every deviation type seen in 2 or more DIFFERENT patients at the site
3. total_points       = sum of step 1 + step 2
4. points_per_patient = total_points / patients at the site
       (so a big site is not penalised just for having more patients)
5. risk_score         = min(100, points_per_patient / SCORE_CAP_POINTS_PER_PATIENT * 100)
                        rounded to a whole number
       The cap is fixed, so a score does not depend on how other sites did.
6. risk_level         0-30 LOW, 31-60 MEDIUM, 61-100 HIGH

The algorithm never looks at specific site IDs.

PROTOTYPE NOTICE: simplified hackathon scoring on synthetic data. Not a
validated risk model and not for real clinical or regulatory decisions.
"""

import math

import pandas as pd

import config
from core.deviation_detector import detect_deviations
from core.severity import add_severity
from utils.data_loader import load_patients, load_protocol

# ---------------------------------------------------------------------------
# Risk factors: every point a site earns belongs to exactly one factor
# ---------------------------------------------------------------------------
FACTOR_DOSING = "Dosing errors"
FACTOR_PROHIBITED_MEDICATION = "Prohibited medications"
FACTOR_VISIT_TIMING = "Late or missed visits"
FACTOR_DOCUMENTATION = "Missing documentation"
FACTOR_REPEATED_PATTERNS = "Repeated patterns"

FACTOR_BY_DEVIATION_TYPE = {
    config.INCORRECT_DOSE: FACTOR_DOSING,
    config.PROHIBITED_MEDICATION: FACTOR_PROHIBITED_MEDICATION,
    config.MISSED_VISIT: FACTOR_VISIT_TIMING,
    config.OUT_OF_WINDOW_VISIT: FACTOR_VISIT_TIMING,
    config.MISSING_DOCUMENTATION: FACTOR_DOCUMENTATION,
}

# Column in the site table that holds each factor's points (in display order)
FACTOR_POINT_COLUMNS = {
    FACTOR_DOSING: "dosing_points",
    FACTOR_PROHIBITED_MEDICATION: "prohibited_medication_points",
    FACTOR_VISIT_TIMING: "visit_timing_points",
    FACTOR_DOCUMENTATION: "documentation_points",
    FACTOR_REPEATED_PATTERNS: "repeated_pattern_points",
}

SITE_RISK_COLUMNS = [
    "site_id",
    "patients",
    "total_deviations",
    "major_deviations",
    "minor_deviations",
    "administrative_deviations",
    "dosing_errors",
    "prohibited_medication_incidents",
    "late_or_missed_visits",
    "repeated_patterns",
    "total_points",
    "points_per_patient",
    "risk_score",
    "risk_level",
    # Extra columns that show where the points came from
    "repeated_pattern_types",
    *FACTOR_POINT_COLUMNS.values(),
    "top_risk_factors",
]


class RiskScoringError(ValueError):
    """The inputs or the scoring settings in config.py cannot be used."""


# ---------------------------------------------------------------------------
# Convenience: run the whole analysis from files
# ---------------------------------------------------------------------------
def run_risk_analysis(patients_source=config.DEMO_PATIENTS_PATH, protocol_path=config.PROTOCOL_PATH):
    """
    Load data, detect deviations, classify severity and score sites.
    Returns a dict with: protocol, patients, deviations, site_risk.
    """
    protocol = load_protocol(protocol_path)
    patients = load_patients(patients_source)
    deviations = add_severity(detect_deviations(patients, protocol))
    site_risk = calculate_site_risk(deviations, patients)
    return {"protocol": protocol, "patients": patients, "deviations": deviations, "site_risk": site_risk}


# ---------------------------------------------------------------------------
# Step 1: points for one deviation
# ---------------------------------------------------------------------------
def deviation_points(severity, deviation_type):
    """Severity points + type bonus for a single deviation."""
    if severity not in config.SEVERITY_POINTS:
        raise RiskScoringError(f"No points defined in SEVERITY_POINTS for severity '{severity}'.")
    return config.SEVERITY_POINTS[severity] + config.DEVIATION_TYPE_BONUS_POINTS.get(deviation_type, 0)


def add_points(deviations):
    """Copy of the deviations table with a 'points' column."""
    scored = deviations.copy()
    scored["points"] = [
        deviation_points(row["severity"], row["deviation_type"])
        for row in scored.to_dict("records")
    ]
    return scored


# ---------------------------------------------------------------------------
# Step 2: repeated patterns
# ---------------------------------------------------------------------------
def find_repeated_patterns(deviations):
    """
    Deviation types seen in at least REPEATED_PATTERN_MIN_PATIENTS different
    patients at the same site. Returns columns: site_id, deviation_type, patients.
    """
    columns = ["site_id", "deviation_type", "patients"]
    if deviations.empty:
        return pd.DataFrame(columns=columns)

    patients_per_type = (
        deviations.groupby(["site_id", "deviation_type"])["patient_id"]
        .nunique()
        .rename("patients")
        .reset_index()
    )
    repeated = patients_per_type["patients"] >= config.REPEATED_PATTERN_MIN_PATIENTS
    return patients_per_type[repeated].reset_index(drop=True)[columns]


# ---------------------------------------------------------------------------
# Steps 5-6: score and level
# ---------------------------------------------------------------------------
def score_from_points_per_patient(points_per_patient):
    """Scale points per patient to a whole-number 0-100 score."""
    # Same as points_per_patient / cap * 100, but multiplying first avoids
    # tiny decimal errors (e.g. 30.499999 instead of 30.5).
    raw_score = points_per_patient * 100 / config.SCORE_CAP_POINTS_PER_PATIENT
    capped = round(min(100.0, max(0.0, raw_score)), 6)
    return int(math.floor(capped + 0.5))  # normal rounding: 30.5 -> 31


def risk_level(score):
    """0-30 LOW, 31-60 MEDIUM, 61-100 HIGH (limits from config.RISK_LEVELS)."""
    for level, highest_score in config.RISK_LEVELS:
        if score <= highest_score:
            return level
    raise RiskScoringError(f"Score {score} is above the highest level in RISK_LEVELS.")


# ---------------------------------------------------------------------------
# Whole calculation for every site
# ---------------------------------------------------------------------------
def calculate_site_risk(deviations, patients):
    """
    Score every site that appears in the patient records (sites with no
    deviations score 0). Returns one row per site using SITE_RISK_COLUMNS,
    sorted from highest to lowest risk.
    """
    check_scoring_config()

    if patients.empty:
        return pd.DataFrame(columns=SITE_RISK_COLUMNS)

    patients_per_site = patients.groupby("site_id")["patient_id"].nunique()
    _check_deviations_match_patients(deviations, patients_per_site)

    scored = add_points(deviations)
    patterns = find_repeated_patterns(deviations)

    rows = [
        _score_one_site(site_id, patient_count, scored, patterns)
        for site_id, patient_count in patients_per_site.items()
    ]
    site_risk = pd.DataFrame(rows, columns=SITE_RISK_COLUMNS)
    return site_risk.sort_values(
        ["risk_score", "total_points", "site_id"], ascending=[False, False, True]
    ).reset_index(drop=True)


def _score_one_site(site_id, patient_count, scored, patterns):
    site = scored[scored["site_id"] == site_id]
    site_patterns = patterns[patterns["site_id"] == site_id]
    types = site["deviation_type"]
    severities = site["severity"]

    # Where the points come from
    factor_points = {factor: 0 for factor in FACTOR_POINT_COLUMNS}
    for deviation_type, points in site.groupby("deviation_type")["points"].sum().items():
        factor_points[FACTOR_BY_DEVIATION_TYPE[deviation_type]] += int(points)
    factor_points[FACTOR_REPEATED_PATTERNS] = len(site_patterns) * config.REPEATED_PATTERN_BONUS_POINTS

    total_points = sum(factor_points.values())
    points_per_patient = total_points / patient_count
    score = score_from_points_per_patient(points_per_patient)

    row = {
        "site_id": site_id,
        "patients": int(patient_count),
        "total_deviations": len(site),
        "major_deviations": int((severities == config.MAJOR).sum()),
        "minor_deviations": int((severities == config.MINOR).sum()),
        "administrative_deviations": int((severities == config.ADMINISTRATIVE).sum()),
        "dosing_errors": int((types == config.INCORRECT_DOSE).sum()),
        "prohibited_medication_incidents": int((types == config.PROHIBITED_MEDICATION).sum()),
        "late_or_missed_visits": int(types.isin([config.MISSED_VISIT, config.OUT_OF_WINDOW_VISIT]).sum()),
        "repeated_patterns": len(site_patterns),
        "total_points": total_points,
        "points_per_patient": round(points_per_patient, 2),
        "risk_score": score,
        "risk_level": risk_level(score),
        "repeated_pattern_types": ", ".join(site_patterns["deviation_type"]),
    }
    for factor, column in FACTOR_POINT_COLUMNS.items():
        row[column] = factor_points[factor]
    row["top_risk_factors"] = format_risk_factors(top_risk_factors(row))
    return row


# ---------------------------------------------------------------------------
# Top contributing factors
# ---------------------------------------------------------------------------
def top_risk_factors(site_row, count=None):
    """
    The factors contributing the most points to a site, biggest first.
    `site_row` is one row of the site risk table (dict or pandas Series).
    Returns a list of dicts: {"factor", "points", "share_pct"}. Factors with
    0 points are left out.
    """
    count = config.TOP_RISK_FACTORS_COUNT if count is None else count
    total = site_row["total_points"]
    if total == 0:
        return []

    factors = [
        {"factor": factor, "points": int(site_row[column]), "share_pct": round(100 * site_row[column] / total)}
        for factor, column in FACTOR_POINT_COLUMNS.items()
        if site_row[column] > 0
    ]
    # sorted() keeps FACTOR_POINT_COLUMNS order for ties
    factors = sorted(factors, key=lambda item: item["points"], reverse=True)
    return factors[:count]


def format_risk_factors(factors):
    """[{'factor': 'Dosing errors', 'points': 105, 'share_pct': 51}] -> 'Dosing errors: 105 pts (51%)'"""
    if not factors:
        return "None"
    return "; ".join(
        f"{item['factor']}: {item['points']} {'pt' if item['points'] == 1 else 'pts'} ({item['share_pct']}%)"
        for item in factors
    )


# ---------------------------------------------------------------------------
# Input and configuration checks
# ---------------------------------------------------------------------------
def _check_deviations_match_patients(deviations, patients_per_site):
    unknown_sites = sorted(set(deviations["site_id"]) - set(patients_per_site.index))
    if unknown_sites:
        raise RiskScoringError(
            "Deviations refer to site(s) with no patient records: " + ", ".join(unknown_sites)
        )
    if "severity" not in deviations.columns:
        raise RiskScoringError("Deviations need a 'severity' column. Run add_severity() first.")
    unknown_types = sorted(set(deviations["deviation_type"]) - set(FACTOR_BY_DEVIATION_TYPE))
    if unknown_types:
        raise RiskScoringError("No risk factor defined for deviation type(s): " + ", ".join(unknown_types))


def check_scoring_config():
    """Stop with a clear message if the scoring settings in config.py don't make sense."""
    problems = []

    missing_levels = [level for level in config.SEVERITY_LEVELS if level not in config.SEVERITY_POINTS]
    if missing_levels:
        problems.append("SEVERITY_POINTS has no points for: " + ", ".join(missing_levels))

    if config.SCORE_CAP_POINTS_PER_PATIENT <= 0:
        problems.append("SCORE_CAP_POINTS_PER_PATIENT must be greater than 0")

    if config.REPEATED_PATTERN_MIN_PATIENTS < 1:
        problems.append("REPEATED_PATTERN_MIN_PATIENTS must be at least 1")

    limits = [highest for _, highest in config.RISK_LEVELS]
    if not limits or limits != sorted(limits) or limits[-1] != 100:
        problems.append("RISK_LEVELS limits must go from low to high and end at 100")

    if problems:
        raise RiskScoringError("Risk scoring settings in config.py have problems:\n- " + "\n- ".join(problems))
