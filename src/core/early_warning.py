"""
Early warning detection.

Looks for patterns that explain WHY a site is risky or is becoming risky.
Warnings never change the risk score - they sit alongside it.

Warnings (thresholds in config.py)
----------------------------------
A. Repeated dosing errors
     WARNING_REPEATED_DOSING_MIN or more dosing deviations at the site.
B. Repeated prohibited medications
     WARNING_REPEATED_PROHIBITED_MED_MIN or more prohibited-medication incidents.
C. Increasing deviation trend
     Protocol visits are split in half: "early" (first half) and "later"
     (second half; with an odd number of visits the middle one is left out).
     Trigger when later >= WARNING_TREND_MULTIPLIER x early
             AND  later - early >= WARNING_TREND_MIN_INCREASE.
D. Unusually high deviation rate
     deviation rate = deviations / expected visits (patients x protocol visits).
     Trigger when the site's rate is more than WARNING_HIGH_RATE_MULTIPLIER x
     the study-wide rate.
E. Top contributing factors
     Not a trigger: every site's biggest point contributors are listed and used
     in a one-sentence headline.

The algorithm never looks at specific site IDs.

PROTOTYPE NOTICE: simplified hackathon rules on synthetic data, not for real
clinical or regulatory decisions.
"""

import pandas as pd

import config
from core.risk_scoring import (
    FACTOR_DOCUMENTATION,
    FACTOR_DOSING,
    FACTOR_PROHIBITED_MEDICATION,
    FACTOR_REPEATED_PATTERNS,
    FACTOR_VISIT_TIMING,
    top_risk_factors,
)

REPEATED_DOSING = "Repeated dosing errors"
REPEATED_PROHIBITED_MEDICATION = "Repeated prohibited medications"
INCREASING_TREND = "Increasing deviation trend"
HIGH_DEVIATION_RATE = "Unusually high deviation rate"

WARNING_TYPES = [REPEATED_DOSING, REPEATED_PROHIBITED_MEDICATION, INCREASING_TREND, HIGH_DEVIATION_RATE]

WARNING_COLUMNS = ["site_id", "warning_type", "message"]

SITE_WARNING_COLUMNS = [
    "site_id",
    "risk_score",
    "risk_level",
    "warning_count",
    "warning_types",
    "headline",
    "top_risk_factors",
]

# How each factor is described in the headline sentence
FACTOR_PHRASES = {
    FACTOR_DOSING: "dosing deviations",
    FACTOR_PROHIBITED_MEDICATION: "prohibited medication incidents",
    FACTOR_VISIT_TIMING: "late or missed visits",
    FACTOR_DOCUMENTATION: "documentation gaps",
}

# Words used for each risk level in the headline
LEVEL_WORDS = {"LOW": "low", "MEDIUM": "moderate", "HIGH": "elevated"}


# ---------------------------------------------------------------------------
# Supporting calculations
# ---------------------------------------------------------------------------
def split_visits(protocol):
    """Return (early_visit_names, later_visit_names) - the first and second half of the schedule."""
    names = [visit["visit"] for visit in protocol["visits"]]
    half = len(names) // 2
    return names[:half], names[len(names) - half:]


def visit_trend(deviations, site_ids, protocol):
    """Deviation counts at early and later visits for each site."""
    early_visits, later_visits = split_visits(protocol)
    rows = []
    for site_id in site_ids:
        site_visits = deviations.loc[deviations["site_id"] == site_id, "visit"]
        rows.append({
            "site_id": site_id,
            "early_deviations": int(site_visits.isin(early_visits).sum()),
            "later_deviations": int(site_visits.isin(later_visits).sum()),
        })
    return pd.DataFrame(rows, columns=["site_id", "early_deviations", "later_deviations"])


def deviation_rates(site_risk, protocol):
    """
    Deviations per expected visit for each site, plus the study-wide rate.
    Returns (DataFrame with site_id, expected_visits, deviation_rate; study_rate).
    """
    visits_per_patient = len(protocol["visits"])
    rates = site_risk[["site_id", "patients", "total_deviations"]].copy()
    rates["expected_visits"] = rates["patients"] * visits_per_patient
    rates["deviation_rate"] = rates["total_deviations"] / rates["expected_visits"]

    total_expected = rates["expected_visits"].sum()
    study_rate = rates["total_deviations"].sum() / total_expected if total_expected else 0.0
    return rates[["site_id", "expected_visits", "deviation_rate"]], study_rate


def is_increasing_trend(early, later):
    """True when later visits have meaningfully more deviations than early visits."""
    return (
        later >= config.WARNING_TREND_MULTIPLIER * early
        and later - early >= config.WARNING_TREND_MIN_INCREASE
    )


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------
def detect_early_warnings(site_risk, deviations, protocol):
    """
    Check every site for warnings A-D.
    `site_risk` comes from calculate_site_risk(), `deviations` from add_severity().
    Returns a DataFrame with WARNING_COLUMNS (one row per warning).
    """
    if site_risk.empty:
        return pd.DataFrame(columns=WARNING_COLUMNS)

    early_visits, later_visits = split_visits(protocol)
    trends = visit_trend(deviations, site_risk["site_id"], protocol).set_index("site_id")
    rates, study_rate = deviation_rates(site_risk, protocol)
    rates = rates.set_index("site_id")

    warnings = []
    for site in site_risk.to_dict("records"):
        site_id = site["site_id"]
        site_deviations = deviations[deviations["site_id"] == site_id]

        # A. Repeated dosing errors
        dosing = site["dosing_errors"]
        if dosing >= config.WARNING_REPEATED_DOSING_MIN:
            patients = _patients_with(site_deviations, config.INCORRECT_DOSE)
            warnings.append(_warning(site_id, REPEATED_DOSING, (
                f"{dosing} dosing errors across {patients} patient(s) "
                f"(warning starts at {config.WARNING_REPEATED_DOSING_MIN})."
            )))

        # B. Repeated prohibited medications
        prohibited = site["prohibited_medication_incidents"]
        if prohibited >= config.WARNING_REPEATED_PROHIBITED_MED_MIN:
            patients = _patients_with(site_deviations, config.PROHIBITED_MEDICATION)
            warnings.append(_warning(site_id, REPEATED_PROHIBITED_MEDICATION, (
                f"{prohibited} prohibited medication incidents across {patients} patient(s) "
                f"(warning starts at {config.WARNING_REPEATED_PROHIBITED_MED_MIN})."
            )))

        # C. Increasing deviation trend
        early = trends.loc[site_id, "early_deviations"]
        later = trends.loc[site_id, "later_deviations"]
        if early_visits and is_increasing_trend(early, later):
            warnings.append(_warning(site_id, INCREASING_TREND, (
                f"Deviations rose from {early} at early visits ({', '.join(early_visits)}) "
                f"to {later} at later visits ({', '.join(later_visits)})."
            )))

        # D. Unusually high deviation rate
        site_rate = rates.loc[site_id, "deviation_rate"]
        if study_rate > 0 and site_rate > config.WARNING_HIGH_RATE_MULTIPLIER * study_rate:
            warnings.append(_warning(site_id, HIGH_DEVIATION_RATE, (
                f"{site_rate:.2f} deviations per expected visit "
                f"({site['total_deviations']} across {rates.loc[site_id, 'expected_visits']} visits), "
                f"{site_rate / study_rate:.1f}x the study average of {study_rate:.2f}."
            )))

    return pd.DataFrame(warnings, columns=WARNING_COLUMNS)


def summarize_site_warnings(site_risk, warnings):
    """
    One row per site: score, level, how many warnings, a one-sentence headline
    and the top contributing factors (warning E). Same order as site_risk.
    """
    rows = []
    for site in site_risk.to_dict("records"):
        types = warnings.loc[warnings["site_id"] == site["site_id"], "warning_type"].tolist()
        rows.append({
            "site_id": site["site_id"],
            "risk_score": site["risk_score"],
            "risk_level": site["risk_level"],
            "warning_count": len(types),
            "warning_types": ", ".join(types) if types else "None",
            "headline": build_headline(site, types),
            "top_risk_factors": site["top_risk_factors"],
        })
    return pd.DataFrame(rows, columns=SITE_WARNING_COLUMNS)


def build_headline(site, warning_types):
    """
    One plain-English sentence explaining the site's risk, e.g.
    "Repeated dosing deviations and repeated prohibited medication incidents
     are driving elevated site risk."
    """
    if site["total_points"] == 0:
        return "No deviations detected; no early warning signals."

    main_factors = [
        item["factor"] for item in top_risk_factors(site)
        if item["factor"] != FACTOR_REPEATED_PATTERNS
    ][:2]

    phrases = []
    for factor in main_factors:
        phrase = FACTOR_PHRASES[factor]
        if (factor == FACTOR_DOSING and REPEATED_DOSING in warning_types) or (
            factor == FACTOR_PROHIBITED_MEDICATION and REPEATED_PROHIBITED_MEDICATION in warning_types
        ):
            phrase = "repeated " + phrase
        phrases.append(phrase)

    level_word = LEVEL_WORDS.get(site["risk_level"], site["risk_level"].lower())
    verb = "are the main contributors to" if site["risk_level"] == "LOW" else "are driving"
    sentence = " and ".join(phrases)
    headline = f"{sentence[0].upper()}{sentence[1:]} {verb} {level_word} site risk."

    if INCREASING_TREND in warning_types:
        headline += " Deviations are increasing at later visits."
    if not warning_types:
        headline += " No early warning signals."
    return headline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _patients_with(site_deviations, deviation_type):
    return site_deviations.loc[site_deviations["deviation_type"] == deviation_type, "patient_id"].nunique()


def _warning(site_id, warning_type, message):
    return {"site_id": site_id, "warning_type": warning_type, "message": message}
