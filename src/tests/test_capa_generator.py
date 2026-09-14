"""
Phase 6 tests: CAPA report generation.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v
"""

import pandas as pd
import pytest

import config
from core import capa_generator as capa
from core.early_warning import (
    HIGH_DEVIATION_RATE,
    INCREASING_TREND,
    REPEATED_DOSING,
    REPEATED_PROHIBITED_MEDICATION,
    WARNING_COLUMNS,
)
from core.risk_scoring import calculate_site_risk
from utils import dashboard_data as data

DATE = "2026-09-14"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def demo():
    result, error = data.analyze_source(config.DEMO_PATIENTS_PATH)
    assert error is None
    return result


def site_inputs(result, site_id):
    details = data.site_details(result, site_id)
    return details["row"], details["warnings"], details["deviations"]


def demo_plan(result, site_id):
    return capa.build_capa_plan(*site_inputs(result, site_id))


def demo_report(result, site_id):
    return capa.build_capa_report(*site_inputs(result, site_id), generated_on=DATE)


def section(report, heading):
    """Text between '### heading' and the next '###' (or the footer)."""
    start = report.index(f"### {heading}")
    rest = report[start + len(heading) + 4:]
    end = min(position for position in (rest.find("\n### "), rest.find("\n---")) if position != -1)
    return rest[:end]


def tiny_site(items, patients=4, warnings=()):
    """Build inputs for a hand-made site. items: (patient, deviation_type, severity)."""
    deviations = pd.DataFrame(
        [{"patient_id": p, "site_id": "SITE-X", "visit": "Visit 2", "deviation_type": t,
          "severity": s, "explanation": f"{t} for {p}"} for p, t, s in items],
        columns=["patient_id", "site_id", "visit", "deviation_type", "severity", "explanation"],
    )
    patient_table = pd.DataFrame({"patient_id": [f"P{n}" for n in range(1, patients + 1)], "site_id": "SITE-X"})
    row = calculate_site_risk(deviations, patient_table).iloc[0].to_dict()
    site_warnings = pd.DataFrame(
        [{"site_id": "SITE-X", "warning_type": w, "message": f"{w} message"} for w in warnings],
        columns=WARNING_COLUMNS,
    )
    return row, site_warnings, deviations


# ---------------------------------------------------------------------------
# Every report: header, Markdown and disclaimers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("site_id", ["SITE-104", "SITE-107", "SITE-105"])
def test_report_header_and_disclaimers(demo, site_id):
    report = demo_report(demo, site_id)
    assert report.startswith("# TrialGuard\n## CAPA / Corrective Action Report\n")
    assert f"- **Site:** {site_id}" in report
    assert f"- **Generated:** {DATE}" in report
    assert "Prototype recommendations, not regulatory advice." in report
    assert "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved." in report
    assert report.endswith("\n")


def test_report_is_deterministic(demo):
    assert demo_report(demo, "SITE-104") == demo_report(demo, "SITE-104")


def test_generated_line_is_optional(demo):
    report = capa.build_capa_report(*site_inputs(demo, "SITE-104"))
    assert "Generated:" not in report


def test_report_does_not_change_inputs(demo):
    row, warnings, deviations = site_inputs(demo, "SITE-104")
    before = deviations.copy()
    capa.build_capa_report(row, warnings, deviations)
    pd.testing.assert_frame_equal(deviations, before)


def test_markdown_table_is_well_formed(demo):
    table_lines = [line for line in section(demo_report(demo, "SITE-104"), "Detected deviations").splitlines()
                   if line.startswith("|")]
    assert table_lines[0] == "| Patient | Visit | Deviation type | Severity | Explanation |"
    assert table_lines[1] == "|---|---|---|---|---|"
    assert len(table_lines) == 2 + 14
    assert all(line.count("|") == 6 for line in table_lines)


def test_pipe_characters_in_cells_are_escaped():
    row, warnings, deviations = tiny_site([("P1", config.INCORRECT_DOSE, config.MAJOR)])
    deviations.loc[0, "explanation"] = "dose A | dose B"
    report = capa.build_capa_report(row, warnings, deviations)
    assert "dose A \\| dose B" in report


def test_download_content_compatibility(demo):
    report = demo_report(demo, "SITE-104")
    downloaded = report.encode("utf-8")
    assert downloaded.decode("utf-8") == report
    assert capa.capa_file_name("SITE-104") == "trialguard_capa_SITE-104.md"
    assert capa.capa_file_name("Site 7/A") == "trialguard_capa_Site_7_A.md"


# ---------------------------------------------------------------------------
# HIGH-risk site: SITE-104
# ---------------------------------------------------------------------------
def test_site_104_plan(demo):
    plan = demo_plan(demo, "SITE-104")
    assert (plan["risk_score"], plan["risk_level"], plan["needs_capa"]) == (68, "HIGH", True)
    assert len(plan["deviation_rows"]) == 14
    assert [w["warning_type"] for w in plan["warnings"]] == [
        REPEATED_DOSING, REPEATED_PROHIBITED_MEDICATION, INCREASING_TREND, HIGH_DEVIATION_RATE,
    ]


def test_site_104_executive_summary(demo):
    summary = demo_plan(demo, "SITE-104")["summary"]
    assert summary.startswith("SITE-104 has a HIGH risk score of 68/100.")
    assert "14 protocol deviation(s) were detected affecting 11 of 12 patients" in summary
    assert "(12 Major, 0 Minor, 2 Administrative)" in summary
    assert "4 early warning(s)" in summary


def test_site_104_affected_patients(demo):
    plan = demo_plan(demo, "SITE-104")
    assert plan["affected_patients"] == [
        "PT-104-02", "PT-104-03", "PT-104-04", "PT-104-05", "PT-104-06", "PT-104-07",
        "PT-104-08", "PT-104-09", "PT-104-10", "PT-104-11", "PT-104-12",
    ]
    assert "11 patient(s): PT-104-02, PT-104-03" in demo_report(demo, "SITE-104")


def test_site_104_deviations_have_severity_most_severe_first(demo):
    rows = demo_plan(demo, "SITE-104")["deviation_rows"]
    assert [row["Severity"] for row in rows] == ["Major"] * 12 + ["Administrative"] * 2
    first = rows[0]
    assert first == {
        "Patient": "PT-104-02", "Visit": "Visit 2", "Deviation type": "Incorrect dose",
        "Severity": "Major", "Explanation": "Dose recorded as 20 mg; the protocol requires 10 mg.",
    }


def test_site_104_contributing_issues(demo):
    plan = demo_plan(demo, "SITE-104")
    assert [item["issue"] for item in plan["issues"]] == [
        "Dosing procedure or dose verification",
        "Medication eligibility/review process",
        "Site processes not keeping pace as the study progresses",
        "Overall site process adherence",
    ]
    assert "early warning: Repeated dosing errors" in plan["issues"][0]["evidence"]
    assert "7 deviation(s)" in plan["issues"][0]["evidence"]
    # Visit timing (2%) and documentation (0%) are too small to be treated as process issues
    assert plan["minor_items"] == [
        "Late or missed visits: 1 deviation(s), 4 risk points (2%)",
        "Missing documentation: 1 deviation(s), 1 risk point (<1%)",
    ]
    report = demo_report(demo, "SITE-104")
    assert "### Likely contributing issues (rule-based hypotheses)" in report
    assert "not proven root causes" in report


def test_site_104_corrective_actions_focus_on_dosing_and_medication(demo):
    actions = demo_plan(demo, "SITE-104")["corrective_actions"]
    assert actions[:6] == [
        "Verify recent dosing records.",
        "Review dose calculation and administration procedures.",
        "Retrain relevant site staff if required.",
        "Review medication reconciliation procedures.",
        "Verify prohibited-medication screening.",
        "Retrain staff on protocol medication restrictions.",
    ]
    assert capa.MINOR_ITEMS_ACTION in actions
    assert "Increase follow-up for patients at risk of missing visits." not in actions


def test_site_104_preventive_actions(demo):
    actions = demo_plan(demo, "SITE-104")["preventive_actions"]
    assert "Add a second-person verification step for dosing." in actions
    assert "Introduce periodic medication review against the protocol's prohibited list." in actions
    assert "Perform periodic site-level deviation review." in actions
    assert len(actions) == len(set(actions))  # no duplicates
    assert "Use visit-window reminders." not in actions


def test_site_104_monitoring(demo):
    report = demo_report(demo, "SITE-104")
    assert section(report, "Monitoring recommendation").strip() == (
        "Recommend prompt enhanced monitoring/review of this site."
    )


# ---------------------------------------------------------------------------
# MEDIUM-risk site: SITE-107
# ---------------------------------------------------------------------------
def test_site_107_plan(demo):
    plan = demo_plan(demo, "SITE-107")
    assert (plan["risk_score"], plan["risk_level"], plan["needs_capa"]) == (52, "MEDIUM", True)
    assert len(plan["deviation_rows"]) == 15
    assert len(plan["affected_patients"]) == 12
    assert plan["minor_items"] == []


def test_site_107_focuses_on_visits(demo):
    plan = demo_plan(demo, "SITE-107")
    assert plan["issues"][0]["issue"] == "Visit scheduling or site follow-up capacity"
    assert "15 deviation(s) in 'Late or missed visits'" in plan["issues"][0]["evidence"]
    assert plan["corrective_actions"][:3] == [
        "Review visit scheduling and patient follow-up.",
        "Identify recurring scheduling bottlenecks.",
        "Increase follow-up for patients at risk of missing visits.",
    ]
    assert "Use visit-window reminders." in plan["preventive_actions"]
    all_actions = " ".join(plan["corrective_actions"] + plan["preventive_actions"]).lower()
    assert "dos" not in all_actions          # nothing about dosing
    assert "medication" not in all_actions   # nothing about medications


def test_site_107_monitoring(demo):
    assert demo_plan(demo, "SITE-107")["monitoring"] == "Recommend increased remote monitoring and closer follow-up."


def test_site_107_missed_visit_without_record_is_listed(demo):
    rows = demo_plan(demo, "SITE-107")["deviation_rows"]
    missed = [row for row in rows if row["Deviation type"] == "Missed visit"]
    assert {row["Patient"] for row in missed} == {"PT-107-02", "PT-107-11", "PT-107-12"}
    assert all(row["Severity"] == "Major" for row in missed)


# ---------------------------------------------------------------------------
# Clean site: SITE-105
# ---------------------------------------------------------------------------
def test_clean_site_needs_no_capa(demo):
    row, warnings, deviations = site_inputs(demo, "SITE-105")
    assert not capa.needs_capa(row, warnings)
    plan = capa.build_capa_plan(row, warnings, deviations)
    assert plan["issues"] == []
    assert plan["corrective_actions"] == []
    assert plan["preventive_actions"] == []
    assert plan["affected_patients"] == []


def test_clean_site_report_text(demo):
    report = demo_report(demo, "SITE-105")
    assert capa.NO_CAPA_MESSAGE in report
    assert "No CAPA actions are currently indicated for this site based on the available demo data." in report
    assert "Continue routine monitoring while watching for new deviations." in report
    for heading in ("Corrective actions", "Preventive actions", "Likely contributing issues", "Detected deviations"):
        assert heading not in report


# ---------------------------------------------------------------------------
# Rule mapping on hand-made sites
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "deviation_type, expected_issue, expected_action",
    [
        (config.INCORRECT_DOSE, "Dosing procedure or dose verification", "Verify recent dosing records."),
        (config.PROHIBITED_MEDICATION, "Medication eligibility/review process", "Verify prohibited-medication screening."),
        (config.MISSED_VISIT, "Visit scheduling or site follow-up capacity", "Review visit scheduling and patient follow-up."),
        (config.OUT_OF_WINDOW_VISIT, "Visit scheduling or site follow-up capacity", "Identify recurring scheduling bottlenecks."),
        (config.MISSING_DOCUMENTATION, "Documentation and record-completion process", "Review source documentation workflow."),
    ],
)
def test_each_deviation_type_maps_to_its_issue(deviation_type, expected_issue, expected_action):
    plan = capa.build_capa_plan(*tiny_site([("P1", deviation_type, config.MINOR)]))
    assert [item["issue"] for item in plan["issues"]] == [expected_issue]
    assert expected_action in plan["corrective_actions"]


@pytest.mark.parametrize(
    "warning_type, expected_issue",
    [
        (INCREASING_TREND, "Site processes not keeping pace as the study progresses"),
        (HIGH_DEVIATION_RATE, "Overall site process adherence"),
    ],
)
def test_warnings_add_their_own_issue(warning_type, expected_issue):
    plan = capa.build_capa_plan(*tiny_site([("P1", config.MISSING_DOCUMENTATION, config.ADMINISTRATIVE)],
                                           warnings=[warning_type]))
    assert expected_issue in [item["issue"] for item in plan["issues"]]
    assert "Perform periodic site-level deviation review." in plan["preventive_actions"]


def test_only_actions_for_detected_patterns():
    plan = capa.build_capa_plan(*tiny_site([("P1", config.INCORRECT_DOSE, config.MAJOR)]))
    actions = " ".join(plan["corrective_actions"] + plan["preventive_actions"])
    assert "dosing" in actions
    assert "medication" not in actions.lower()
    assert "visit" not in actions.lower()


def test_small_share_factor_with_repeated_warning_is_still_an_issue(monkeypatch):
    monkeypatch.setattr(capa, "MIN_RISK_SHARE_FOR_ISSUE_PCT", 90)
    plan = capa.build_capa_plan(*tiny_site(
        [("P1", config.INCORRECT_DOSE, config.MAJOR), ("P2", config.MISSED_VISIT, config.MAJOR)],
        warnings=[REPEATED_DOSING],
    ))
    issues = [item["issue"] for item in plan["issues"]]
    assert "Dosing procedure or dose verification" in issues          # kept because of the warning
    assert "Visit scheduling or site follow-up capacity" not in issues  # below the 90% limit
    assert plan["minor_items"][0].startswith("Late or missed visits: 1 deviation(s)")


@pytest.mark.parametrize(
    "level, expected",
    [
        ("HIGH", "Recommend prompt enhanced monitoring/review of this site."),
        ("MEDIUM", "Recommend increased remote monitoring and closer follow-up."),
        ("LOW", "Continue routine monitoring while watching for new deviations."),
    ],
)
def test_monitoring_recommendation_by_level(level, expected):
    row, warnings, deviations = tiny_site([("P1", config.MISSING_DOCUMENTATION, config.ADMINISTRATIVE)])
    row["risk_level"] = level
    assert capa.build_capa_plan(row, warnings, deviations)["monitoring"] == expected


def test_low_site_with_deviations_still_gets_actions():
    row, warnings, deviations = tiny_site([("P1", config.MISSING_DOCUMENTATION, config.ADMINISTRATIVE)], patients=10)
    assert row["risk_level"] == "LOW"
    plan = capa.build_capa_plan(row, warnings, deviations)
    assert plan["needs_capa"]
    assert plan["corrective_actions"]
    assert plan["monitoring"] == "Continue routine monitoring while watching for new deviations."


def test_every_factor_rule_has_issue_and_actions():
    for rules in (capa.ISSUE_RULES_BY_FACTOR, capa.ISSUE_RULES_BY_WARNING):
        for rule in rules.values():
            assert rule["issue"]
            assert rule["corrective"]
            assert rule["preventive"]
