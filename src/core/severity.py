"""
Severity classification.

Takes the deviations table from core/deviation_detector.py and gives every
deviation exactly one severity: Major, Minor or Administrative.

All thresholds and type-to-severity choices live in config.py:

    Deviation type          Severity
    ----------------------  ---------------------------------------------
    Missed visit            Major                (SEVERITY_BY_DEVIATION_TYPE)
    Incorrect dose          Major                (SEVERITY_BY_DEVIATION_TYPE)
    Prohibited medication   Major                (SEVERITY_BY_DEVIATION_TYPE)
    Missing documentation   Administrative       (SEVERITY_BY_DEVIATION_TYPE)
    Out-of-window visit     depends on days outside the window:
                              1-2 days   -> Administrative  (VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE)
                              3-7 days   -> Minor           (VISIT_MINOR_MAX_DAYS_OUTSIDE)
                              over 7     -> Major

This module does not detect deviations and does not score sites.

PROTOTYPE NOTICE: these are simplified hackathon rules, NOT regulatory
determinations, and must not be used for real clinical decisions.
"""

import pandas as pd

import config


class SeverityRuleError(ValueError):
    """A deviation could not be classified, or the rules in config.py are inconsistent."""


def classify_severity(deviation_type, days_outside_window=None):
    """
    Return (severity, rule_explanation) for one deviation.

    Examples:
        classify_severity("Incorrect dose")            -> ("Major", "...")
        classify_severity("Out-of-window visit", 3)    -> ("Minor", "...")
    """
    if deviation_type == config.OUT_OF_WINDOW_VISIT:
        return _classify_out_of_window(days_outside_window)

    if deviation_type in config.SEVERITY_BY_DEVIATION_TYPE:
        severity = config.SEVERITY_BY_DEVIATION_TYPE[deviation_type]
        return severity, f"{deviation_type} is always {severity}"

    raise SeverityRuleError(
        f"No severity rule for deviation type '{deviation_type}'. "
        "Add it to SEVERITY_BY_DEVIATION_TYPE in config.py."
    )


def _classify_out_of_window(days_outside_window):
    if days_outside_window is None or pd.isna(days_outside_window) or days_outside_window <= 0:
        raise SeverityRuleError(
            "An out-of-window visit needs days_outside_window greater than 0 "
            f"(got {days_outside_window!r})."
        )

    admin_max = config.VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE
    minor_max = config.VISIT_MINOR_MAX_DAYS_OUTSIDE
    days = _format_days(days_outside_window)

    if days_outside_window <= admin_max:
        return config.ADMINISTRATIVE, (
            f"{days} day(s) outside window: up to {admin_max} days is {config.ADMINISTRATIVE}"
        )
    if days_outside_window <= minor_max:
        return config.MINOR, (
            f"{days} day(s) outside window: {admin_max + 1} to {minor_max} days is {config.MINOR}"
        )
    return config.MAJOR, (
        f"{days} day(s) outside window: more than {minor_max} days is {config.MAJOR}"
    )


def add_severity(deviations):
    """
    Return a copy of the deviations table with two new columns placed right
    after deviation_type:
        severity       Major / Minor / Administrative
        severity_rule  the rule that produced it, in plain English
    All existing columns are kept unchanged.
    """
    check_severity_config()
    classified = deviations.copy()

    results = [
        classify_severity(row["deviation_type"], row["days_outside_window"])
        for row in classified.to_dict("records")
    ]
    severities = [severity for severity, _ in results]
    rules = [rule for _, rule in results]

    position = classified.columns.get_loc("deviation_type") + 1
    classified.insert(position, "severity", pd.Series(severities, index=classified.index, dtype=object))
    classified.insert(position + 1, "severity_rule", pd.Series(rules, index=classified.index, dtype=object))
    return classified


def check_severity_config():
    """Stop with a clear message if the severity settings in config.py don't make sense."""
    problems = []

    admin_max = config.VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE
    minor_max = config.VISIT_MINOR_MAX_DAYS_OUTSIDE
    if not 0 < admin_max < minor_max:
        problems.append(
            "VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE must be above 0 and below "
            f"VISIT_MINOR_MAX_DAYS_OUTSIDE (got {admin_max} and {minor_max})"
        )

    for deviation_type in config.DEVIATION_TYPES:
        if deviation_type == config.OUT_OF_WINDOW_VISIT:
            continue
        if deviation_type not in config.SEVERITY_BY_DEVIATION_TYPE:
            problems.append(f"SEVERITY_BY_DEVIATION_TYPE has no entry for '{deviation_type}'")

    for deviation_type, severity in config.SEVERITY_BY_DEVIATION_TYPE.items():
        if severity not in config.SEVERITY_LEVELS:
            problems.append(
                f"'{deviation_type}' has severity '{severity}', "
                f"which is not one of {config.SEVERITY_LEVELS}"
            )

    if problems:
        raise SeverityRuleError("Severity settings in config.py have problems:\n- " + "\n- ".join(problems))


def summarize_severity(classified):
    """Counts by severity (all levels shown, even if 0) and a site x severity table."""
    counts = classified["severity"].value_counts()
    by_severity = {level: int(counts.get(level, 0)) for level in config.SEVERITY_LEVELS}
    by_site = (
        pd.crosstab(classified["site_id"], classified["severity"])
        .reindex(columns=config.SEVERITY_LEVELS, fill_value=0)
    )
    return {"by_severity": by_severity, "by_site": by_site}


def _format_days(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)
