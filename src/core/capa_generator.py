"""
CAPA (Corrective and Preventive Action) report generation.

Builds a Markdown CAPA-style report for ONE site from results that earlier
steps have already calculated:

    site_row        one row of the site risk table   (core/risk_scoring.py)
    site_warnings   that site's early warnings        (core/early_warning.py)
    site_deviations that site's classified deviations (core/severity.py)

This module does NOT detect deviations, score sites or raise warnings. It only
looks up which issue areas are present and copies the matching text from the
editable rule tables below (ISSUE_RULES_BY_FACTOR, ISSUE_RULES_BY_WARNING,
MONITORING_BY_LEVEL). The same inputs always give the same report.

Contributing issues are rule-based hypotheses, not proven root causes, and all
actions are prototype recommendations, not regulatory advice.
"""

import pandas as pd

import config
from core.early_warning import (
    HIGH_DEVIATION_RATE,
    INCREASING_TREND,
    REPEATED_DOSING,
    REPEATED_PROHIBITED_MEDICATION,
    build_headline,
)
from core.risk_scoring import (
    FACTOR_BY_DEVIATION_TYPE,
    FACTOR_DOCUMENTATION,
    FACTOR_DOSING,
    FACTOR_POINT_COLUMNS,
    FACTOR_PROHIBITED_MEDICATION,
    FACTOR_VISIT_TIMING,
    top_risk_factors,
)

PROTOTYPE_NOTICE = "Prototype recommendations, not regulatory advice."
DEMO_DISCLAIMER = "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved."
NO_CAPA_MESSAGE = "No CAPA actions are currently indicated for this site based on the available demo data."
ISSUES_HEADING = "Likely contributing issues (rule-based hypotheses)"

# ---------------------------------------------------------------------------
# EDITABLE RULE TABLES
# ---------------------------------------------------------------------------
# A risk factor becomes a "likely contributing issue" (with its own corrective
# and preventive actions) only if it provides at least this share of the site's
# risk points. Smaller contributors are listed as minor items to correct.
MIN_RISK_SHARE_FOR_ISSUE_PCT = 10

MINOR_ITEMS_ACTION = "Correct the individual records for the smaller contributors listed above."

# Used when a risk factor passes MIN_RISK_SHARE_FOR_ISSUE_PCT.
ISSUE_RULES_BY_FACTOR = {
    FACTOR_DOSING: {
        "issue": "Dosing procedure or dose verification",
        "warning": REPEATED_DOSING,
        "corrective": [
            "Verify recent dosing records.",
            "Review dose calculation and administration procedures.",
            "Retrain relevant site staff if required.",
        ],
        "preventive": [
            "Add a second-person verification step for dosing.",
            "Add an automated check that the recorded dose matches the protocol dose.",
        ],
    },
    FACTOR_PROHIBITED_MEDICATION: {
        "issue": "Medication eligibility/review process",
        "warning": REPEATED_PROHIBITED_MEDICATION,
        "corrective": [
            "Review medication reconciliation procedures.",
            "Verify prohibited-medication screening.",
            "Retrain staff on protocol medication restrictions.",
        ],
        "preventive": [
            "Introduce periodic medication review against the protocol's prohibited list.",
            "Add an automated prohibited-medication check at data entry.",
        ],
    },
    FACTOR_VISIT_TIMING: {
        "issue": "Visit scheduling or site follow-up capacity",
        "warning": None,
        "corrective": [
            "Review visit scheduling and patient follow-up.",
            "Identify recurring scheduling bottlenecks.",
            "Increase follow-up for patients at risk of missing visits.",
        ],
        "preventive": [
            "Use visit-window reminders.",
        ],
    },
    FACTOR_DOCUMENTATION: {
        "issue": "Documentation and record-completion process",
        "warning": None,
        "corrective": [
            "Review source documentation workflow.",
            "Complete missing records where appropriate.",
            "Reinforce documentation requirements.",
        ],
        "preventive": [
            "Add automated validation checks before visit submission.",
        ],
    },
}

# Used when one of these early warnings was raised for the site.
ISSUE_RULES_BY_WARNING = {
    INCREASING_TREND: {
        "issue": "Site processes not keeping pace as the study progresses",
        "corrective": [
            "Review the most recent visits first to find what changed at the site.",
        ],
        "preventive": [
            "Perform periodic site-level deviation review.",
        ],
    },
    HIGH_DEVIATION_RATE: {
        "issue": "Overall site process adherence",
        "corrective": [
            "Review site processes against the protocol with the site team.",
        ],
        "preventive": [
            "Perform periodic site-level deviation review.",
        ],
    },
}

MONITORING_BY_LEVEL = {
    "HIGH": "Recommend prompt enhanced monitoring/review of this site.",
    "MEDIUM": "Recommend increased remote monitoring and closer follow-up.",
    "LOW": "Continue routine monitoring while watching for new deviations.",
}

# Columns shown in the detected deviations table
DEVIATION_TABLE_COLUMNS = {
    "patient_id": "Patient",
    "visit": "Visit",
    "deviation_type": "Deviation type",
    "severity": "Severity",
    "explanation": "Explanation",
}


# ---------------------------------------------------------------------------
# Step 1: decide what goes in the report
# ---------------------------------------------------------------------------
def needs_capa(site_row, site_warnings):
    """A CAPA is indicated when the site has any deviation or any early warning."""
    return site_row["total_deviations"] > 0 or len(site_warnings) > 0


def build_capa_plan(site_row, site_warnings, site_deviations):
    """
    Collect every part of the CAPA report as plain Python data (easy to test).
    Returns a dict; see capa_report_markdown() for how it is displayed.
    """
    warning_types = site_warnings["warning_type"].tolist()
    plan = {
        "site_id": site_row["site_id"],
        "risk_score": int(site_row["risk_score"]),
        "risk_level": site_row["risk_level"],
        "needs_capa": needs_capa(site_row, site_warnings),
        "summary": executive_summary(site_row, site_warnings, site_deviations),
        "warnings": site_warnings[["warning_type", "message"]].to_dict("records"),
        "deviation_rows": deviation_rows(site_deviations),
        "affected_patients": sorted(site_deviations["patient_id"].unique().tolist()),
        "issues": [],
        "minor_items": [],
        "corrective_actions": [],
        "preventive_actions": [],
        "monitoring": MONITORING_BY_LEVEL.get(site_row["risk_level"], MONITORING_BY_LEVEL["LOW"]),
    }
    if not plan["needs_capa"]:
        return plan

    rules, minor_items = matching_rules(site_row, warning_types, site_deviations)
    plan["issues"] = [{"issue": rule["issue"], "evidence": rule["evidence"]} for rule in rules]
    plan["minor_items"] = minor_items
    corrective = [action for rule in rules for action in rule["corrective"]]
    if minor_items:
        corrective.append(MINOR_ITEMS_ACTION)
    plan["corrective_actions"] = _unique(corrective)
    plan["preventive_actions"] = _unique([action for rule in rules for action in rule["preventive"]])
    return plan


def matching_rules(site_row, warning_types, site_deviations):
    """
    Decide which rules apply to this site. Returns (rules, minor_items).

    rules, most important first:
      1. risk factors with at least MIN_RISK_SHARE_FOR_ISSUE_PCT of the site's
         risk points (or a matching repeated-pattern warning), biggest first
      2. early warnings that have their own rule (trend, high rate)
    Each rule has: issue, evidence, corrective, preventive.

    minor_items: factors below the share limit, e.g. "Missing documentation: 1 deviation(s)".
    """
    counts = site_deviations["deviation_type"].map(FACTOR_BY_DEVIATION_TYPE).value_counts()
    rules = []
    minor_items = []

    for factor in top_risk_factors(site_row, count=len(FACTOR_POINT_COLUMNS)):
        rule = ISSUE_RULES_BY_FACTOR.get(factor["factor"])
        if rule is None:
            continue  # e.g. "Repeated patterns" has no rule of its own
        deviation_count = int(counts.get(factor["factor"], 0))
        has_warning = rule["warning"] in warning_types
        if factor["share_pct"] < MIN_RISK_SHARE_FOR_ISSUE_PCT and not has_warning:
            share = "<1" if factor["share_pct"] == 0 else factor["share_pct"]  # 1 of 205 points rounds to 0
            minor_items.append(
                f"{factor['factor']}: {deviation_count} deviation(s), {factor['points']} risk "
                f"{'point' if factor['points'] == 1 else 'points'} ({share}%)"
            )
            continue
        evidence = (
            f"{deviation_count} deviation(s) in '{factor['factor']}' "
            f"({factor['points']} risk points, {factor['share_pct']}% of the site total)"
        )
        if has_warning:
            evidence += f"; early warning: {rule['warning']}"
        rules.append({**rule, "evidence": evidence})

    for warning_type in warning_types:
        rule = ISSUE_RULES_BY_WARNING.get(warning_type)
        if rule is not None:
            rules.append({**rule, "evidence": f"early warning: {warning_type}"})

    return rules, minor_items


def executive_summary(site_row, site_warnings, site_deviations):
    """A few plain-English sentences summarising the site."""
    site_id = site_row["site_id"]
    total = int(site_row["total_deviations"])
    if total == 0 and site_warnings.empty:
        return (
            f"{site_id} has a {site_row['risk_level']} risk score of {int(site_row['risk_score'])}/100. "
            "No protocol deviations or early warnings were detected."
        )

    affected = site_deviations["patient_id"].nunique()
    sentences = [
        f"{site_id} has a {site_row['risk_level']} risk score of {int(site_row['risk_score'])}/100.",
        f"{total} protocol deviation(s) were detected affecting {affected} of "
        f"{int(site_row['patients'])} patients ({int(site_row['major_deviations'])} Major, "
        f"{int(site_row['minor_deviations'])} Minor, {int(site_row['administrative_deviations'])} Administrative).",
    ]
    warning_types = site_warnings["warning_type"].tolist()
    if warning_types:
        sentences.append(f"{len(warning_types)} early warning(s): {', '.join(warning_types)}.")
    else:
        sentences.append("No early warnings were raised.")
    sentences.append(build_headline(site_row, warning_types))
    return " ".join(sentences)


def deviation_rows(site_deviations):
    """Deviations for the report table, most severe first."""
    severity_order = {level: number for number, level in enumerate(config.SEVERITY_LEVELS)}
    ordered = site_deviations.assign(_order=site_deviations["severity"].map(severity_order))
    ordered = ordered.sort_values(["_order", "patient_id"], kind="stable")
    return ordered[list(DEVIATION_TABLE_COLUMNS)].rename(columns=DEVIATION_TABLE_COLUMNS).to_dict("records")


# ---------------------------------------------------------------------------
# Step 2: turn the plan into Markdown
# ---------------------------------------------------------------------------
def build_capa_report(site_row, site_warnings, site_deviations, generated_on=None, for_screen=False):
    """
    Build the full Markdown CAPA report for one site.
    for_screen=True gives smaller headings for showing inside the dashboard;
    the content is otherwise identical to the downloadable report.
    """
    plan = build_capa_plan(site_row, site_warnings, site_deviations)
    return capa_report_markdown(plan, generated_on, for_screen)


def capa_report_markdown(plan, generated_on=None, for_screen=False):
    lines = _report_lines(plan, generated_on)
    if for_screen:
        # Replace the big document title with one small heading and make the
        # section headings one level smaller, so they sit under the page's own
        # "CAPA report" heading.
        lines = [f"#### CAPA / Corrective Action Report — {plan['site_id']}"] + [
            "#" + line if line.startswith("### ") else line for line in lines[2:]
        ]
    return "\n".join(lines) + "\n"


def _report_lines(plan, generated_on):
    lines = [
        "# TrialGuard",
        "## CAPA / Corrective Action Report",
        "",
        f"> **{PROTOTYPE_NOTICE}**  ",
        f"> {DEMO_DISCLAIMER}",
        "",
        f"- **Site:** {plan['site_id']}",
        f"- **Risk score:** {plan['risk_score']} / 100",
        f"- **Risk level:** {plan['risk_level']}",
    ]
    if generated_on:
        lines.append(f"- **Generated:** {generated_on}")

    lines += ["", "### Executive summary", "", plan["summary"]]

    if not plan["needs_capa"]:
        lines += ["", "### CAPA status", "", f"**{NO_CAPA_MESSAGE}**"]
        lines += ["", "### Monitoring recommendation", "", plan["monitoring"]]
        lines += _footer()
        return lines

    if plan["warnings"]:
        lines += ["", "### Early warnings", ""]
        lines += [f"- **{w['warning_type']}:** {w['message']}" for w in plan["warnings"]]

    lines += ["", "### Detected deviations", ""]
    if plan["deviation_rows"]:
        headers = list(DEVIATION_TABLE_COLUMNS.values())
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "---|" * len(headers))
        for row in plan["deviation_rows"]:
            lines.append("| " + " | ".join(_table_cell(row[header]) for header in headers) + " |")
    else:
        lines.append("No deviations detected.")

    lines += ["", "### Affected patients", ""]
    patients = plan["affected_patients"]
    lines.append(f"{len(patients)} patient(s): {', '.join(patients)}" if patients else "None.")

    lines += ["", f"### {ISSUES_HEADING}", "",
              "_These are suggested areas to investigate based on the detected patterns. "
              "They are not proven root causes._", ""]
    lines += [f"{number}. **{item['issue']}** — based on {item['evidence']}"
              for number, item in enumerate(plan["issues"], start=1)]
    if plan["minor_items"]:
        lines += ["", f"Smaller contributors (below {MIN_RISK_SHARE_FOR_ISSUE_PCT}% of risk points, "
                      "corrected individually rather than treated as a process issue):", ""]
        lines += [f"- {item}" for item in plan["minor_items"]]

    lines += ["", "### Corrective actions", ""]
    lines += [f"- [ ] {action}" for action in plan["corrective_actions"]]

    lines += ["", "### Preventive actions", ""]
    lines += [f"- [ ] {action}" for action in plan["preventive_actions"]]

    lines += ["", "### Monitoring recommendation", "", plan["monitoring"]]
    lines += _footer()
    return lines


def capa_file_name(site_id):
    """File name for the downloaded report, e.g. trialguard_capa_SITE-104.md"""
    safe = "".join(character if character.isalnum() or character in "-_" else "_" for character in str(site_id))
    return f"trialguard_capa_{safe}.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _footer():
    return [
        "",
        "---",
        "",
        f"_{PROTOTYPE_NOTICE} Generated by the TrialGuard hackathon prototype from rule-based checks. "
        "Severity labels, risk scores and actions are simplified prototype rules, not regulatory "
        f"determinations._  ",
        f"_{DEMO_DISCLAIMER}_",
    ]


def _table_cell(value):
    """Make a value safe for a Markdown table cell."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _unique(items):
    """Remove duplicates but keep the original order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
