"""
TrialGuard - Streamlit dashboard.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m streamlit run src\\app.py

This file only draws the page. All rules live in src/core/ and all data
preparation lives in src/utils/dashboard_data.py:

    CSV -> data_loader -> deviation_detector -> severity -> risk_scoring
        -> early_warning -> capa_generator -> this page

PROTOTYPE: synthetic data, simplified rules. Not for clinical decision-making.
"""

from datetime import date

import streamlit as st

import config
from core import capa_generator
from utils import charts
from utils import dashboard_data as data

st.set_page_config(page_title="TrialGuard", page_icon="🛡️", layout="wide")

DISCLAIMER = (
    "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved."
)
DEMO_SOURCE = "Built-in synthetic demo data"
UPLOAD_SOURCE = "Upload my own CSV"
TRIAL_COMPLETED = "Completed — every patient finished the visit schedule"
TRIAL_ONGOING = "Ongoing — some patients have not reached every visit yet"

# Box style for each risk level's headline (the text inside always names the level too)
HEADLINE_BOX = {"HIGH": st.error, "MEDIUM": st.warning, "LOW": st.info}


# ---------------------------------------------------------------------------
# Cached analysis (re-runs only when the data or options change)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Analysing synthetic demo data...")
def analyse_demo_data():
    return data.analyze_source(config.DEMO_PATIENTS_PATH)


@st.cache_data(show_spinner="Analysing uploaded file...")
def analyse_uploaded_file(file_bytes, assume_schedule_complete):
    return data.analyze_uploaded_bytes(file_bytes, assume_schedule_complete)


# ---------------------------------------------------------------------------
# Header and sidebar
# ---------------------------------------------------------------------------
def show_header():
    st.title("🛡️ TrialGuard")
    st.subheader("Clinical Trial Risk Monitor & Protocol Deviation Detector")
    st.markdown(
        "Compares patient visit records against the trial protocol, detects **protocol deviations** "
        "(missed or late visits, wrong doses, prohibited medications), scores every site's risk "
        "from 0 to 100, raises **early warnings**, and drafts a **CAPA report** for sites that need attention."
    )
    st.markdown(
        "**How to use:** 1️⃣ choose data in the sidebar · 2️⃣ review the study overview · "
        "3️⃣ pick a site in the sidebar and open the **🔍 Site details** tab."
    )
    st.warning(DISCLAIMER, icon="⚠️")


def choose_data_source():
    """Sidebar data choice. Returns (analysis outcome or None, description of the data)."""
    st.sidebar.header("1. Choose data")
    source = st.sidebar.radio("Data source", [DEMO_SOURCE, UPLOAD_SOURCE], label_visibility="collapsed")

    if source == DEMO_SOURCE:
        st.sidebar.caption("Fictional patients and sites. Every patient has finished the visit schedule.")
        return analyse_demo_data(), "Built-in synthetic demo data"

    uploaded = st.sidebar.file_uploader("Patient visit records (CSV file)", type=["csv"])
    trial_status = st.sidebar.radio(
        "Trial status",
        [TRIAL_COMPLETED, TRIAL_ONGOING],
        help=(
            "Completed: a visit with no record counts as a missed visit.\n\n"
            "Ongoing: a visit with no record only counts as missed if the patient already has a "
            "record for a later visit. Visits after a patient's last record are treated as not yet "
            "due. To flag a visit that was definitely missed, add a row with a blank actual_day."
        ),
    )
    show_upload_help()

    if uploaded is None:
        return None, None
    assume_schedule_complete = trial_status == TRIAL_COMPLETED
    status_text = "completed trial" if assume_schedule_complete else "ongoing trial"
    return (
        analyse_uploaded_file(uploaded.getvalue(), assume_schedule_complete),
        f"Uploaded file: {uploaded.name} ({status_text})",
    )


def show_upload_help():
    with st.sidebar.expander("CSV format, example and sample files"):
        st.markdown("One row per patient visit, with these columns:")
        st.markdown(
            "- `patient_id`, `site_id`\n"
            f"- `visit`: one of {', '.join(data.protocol_visit_names()) or 'the protocol visit names'}\n"
            "- `actual_day`: study day of the visit — **leave blank if the visit was missed**\n"
            "- `dose_mg`: number\n"
            f"- `medication`: `{config.NO_MEDICATION_VALUE}` if nothing else; separate several with `;`"
        )
        st.markdown("Example:")
        st.code(
            ",".join(config.REQUIRED_COLUMNS) + "\n"
            "PT-001,SITE-A,Visit 1,0,10,None\n"
            "PT-001,SITE-A,Visit 2,15,10,DrugA\n"
            "PT-001,SITE-A,Visit 3,,,",
            language="text",
        )
        st.caption("Sample files to try the upload:")
        st.download_button(
            "Download demo data (valid CSV)",
            data=config.DEMO_PATIENTS_PATH.read_bytes(),
            file_name="trialguard_demo_patients.csv",
            mime="text/csv",
        )
        st.download_button(
            "Download sample invalid CSV",
            data=config.SAMPLE_INVALID_UPLOAD_PATH.read_bytes(),
            file_name="sample_invalid_upload.csv",
            mime="text/csv",
        )


def choose_site(result):
    st.sidebar.header("2. Choose a site")
    selected = st.sidebar.selectbox("Site", data.site_options(result["site_risk"]))
    st.sidebar.caption("Sites are listed from highest to lowest risk. Details appear in the 🔍 Site details tab.")
    return selected


# ---------------------------------------------------------------------------
# Study overview
# ---------------------------------------------------------------------------
def show_data_messages(result, data_description):
    st.caption(f"Data: {data_description} · Protocol: {result['protocol'].get('protocol_id', 'unnamed')}")
    for note in result["data_notes"]:
        st.info(f"**Data preparation:** {note}", icon="ℹ️")
    for warning in result["data_warnings"]:
        st.warning(f"**Data check:** {warning}", icon="⚠️")
    if not result["assume_schedule_complete"]:
        st.info(
            f"**Ongoing trial:** {result['visits_not_yet_due']} visit(s) after patients' last records "
            "are treated as not yet due and are not counted as missed.",
            icon="ℹ️",
        )


def show_study_metrics(result):
    metrics = data.study_metrics(result)
    # Two rows of three so the full labels fit on a laptop screen
    first = st.columns(3)
    first[0].metric("Sites", metrics["total_sites"])
    first[1].metric("Patients", metrics["total_patients"])
    first[2].metric("Protocol Deviations", metrics["total_deviations"])
    second = st.columns(3)
    second[0].metric("🔴 HIGH-Risk Sites", metrics["high_risk_sites"])
    second[1].metric("🟠 MEDIUM-Risk Sites", metrics["medium_risk_sites"])
    second[2].metric("⚠️ Sites with Early Warnings", metrics["sites_with_warnings"])


def show_overview_tab(result, selected_site):
    site_risk = result["site_risk"]

    if selected_site != data.ALL_SITES:
        st.info(
            f"**{selected_site}** is selected. Open the **🔍 Site details** tab above for its "
            "early warnings and CAPA report.",
            icon="👉",
        )

    st.subheader("Site risk ranking")
    st.caption(
        "Highest risk first. Risk levels: 🟢 LOW 0–30 · 🟠 MEDIUM 31–60 · 🔴 HIGH 61–100. "
        "Scores are simplified prototype rules."
    )
    st.dataframe(
        data.site_overview_table(site_risk, result["site_summary"]),
        hide_index=True,
        width="stretch",
        # Plain numbers: a progress bar here would be red (the theme colour) even for LOW sites
        column_config={"Risk Score": st.column_config.NumberColumn("Risk Score (0–100)", format="%d")},
    )
    st.markdown("**Risk score by site** (dashed lines mark the LOW / MEDIUM / HIGH limits)")
    highlight = None if selected_site == data.ALL_SITES else selected_site
    st.plotly_chart(charts.site_risk_chart(site_risk, highlight), width="stretch")

    st.subheader("Sites with early warnings")
    flagged = result["site_summary"][result["site_summary"]["warning_count"] > 0]
    if flagged.empty:
        st.success("No early warnings detected at any site.", icon="✅")
    else:
        st.dataframe(
            flagged.assign(risk_level=flagged["risk_level"].map(data.level_label))[
                ["site_id", "risk_level", "risk_score", "warning_count", "warning_types", "headline"]
            ].rename(columns={
                "site_id": "Site", "risk_score": "Risk Score", "risk_level": "Risk Level",
                "warning_count": "Warnings", "warning_types": "Warning types", "headline": "Why",
            }),
            hide_index=True,
            width="stretch",
            column_config={
                "Warning types": st.column_config.TextColumn("Warning types", width="medium"),
                "Why": st.column_config.TextColumn("Why", width="large"),
            },
        )

    st.subheader("Deviations across the study")
    deviations = result["deviations"]
    if deviations.empty:
        st.success("No protocol deviations detected in this dataset.", icon="✅")
        return
    type_column, severity_column = st.columns(2)
    with type_column:
        st.markdown("**By deviation type**")
        by_type = data.count_by(deviations, "deviation_type", config.DEVIATION_TYPES)
        st.plotly_chart(
            charts.horizontal_count_chart(by_type["deviation_type"], by_type["count"], "Deviations"),
            width="stretch",
        )
    with severity_column:
        st.markdown("**By severity** (Major · Minor · Administrative)")
        by_severity = data.count_by(deviations, "severity", config.SEVERITY_LEVELS)
        st.plotly_chart(
            charts.horizontal_count_chart(by_severity["severity"], by_severity["count"], "Deviations"),
            width="stretch",
        )


# ---------------------------------------------------------------------------
# Site details
# ---------------------------------------------------------------------------
def show_site_details_tab(result, site_id):
    if site_id == data.ALL_SITES:
        st.info("Choose a site in the sidebar (**2. Choose a site**) to see its risk score, "
                "early warnings, CAPA report and deviation records.", icon="👈")
        return

    details = data.site_details(result, site_id)
    row = details["row"]
    level = row["risk_level"]

    st.header(f"{site_id} — {data.level_label(level)} risk")
    HEADLINE_BOX.get(level, st.info)(f"**{level} risk ({row['risk_score']}/100):** {details['headline']}")

    first = st.columns(4)
    first[0].metric("Risk Score", f"{row['risk_score']} / 100")
    first[1].metric("Risk Level", data.level_label(level))
    first[2].metric("Patients", row["patients"])
    first[3].metric("Affected Patients", details["affected_patients"])
    second = st.columns(4)
    second[0].metric("Total Deviations", row["total_deviations"])
    second[1].metric("Major", row["major_deviations"])
    second[2].metric("Minor", row["minor_deviations"])
    second[3].metric("Administrative", row["administrative_deviations"])

    warnings = details["warnings"]
    st.subheader(f"Early warnings ({len(warnings)})")
    if warnings.empty:
        st.success("No early warnings detected for this site.", icon="✅")
    else:
        st.caption("Warnings explain the risk score; they do not change it.")
        for number, warning in enumerate(warnings.to_dict("records"), start=1):
            st.warning(
                f"**Warning {number} of {len(warnings)} — {warning['warning_type']}:** {warning['message']}",
                icon="⚠️",
            )

    st.subheader("What is driving this site's risk")
    if not details["top_factors"]:
        st.success("This site has no risk points: no deviations were detected.", icon="✅")
    else:
        factor_column, chart_column = st.columns([1, 1])
        with factor_column:
            st.markdown("**Top contributing factors**")
            st.markdown("\n".join(
                f"{number}. **{item['factor']}** — {item['points']} risk "
                f"{'point' if item['points'] == 1 else 'points'} ({item['share_pct']}% of the total)"
                for number, item in enumerate(details["top_factors"], start=1)
            ))
            # "Repeated patterns" has points but no deviations of its own: show "—" instead of "None"
            breakdown = details["breakdown"].assign(
                Deviations=details["breakdown"]["Deviations"].astype(str).replace("<NA>", "—")
            )
            st.dataframe(breakdown, hide_index=True, width="stretch")
        with chart_column:
            st.markdown("**Risk points by factor**")
            st.plotly_chart(charts.risk_factor_chart(details["breakdown"]), width="stretch")

    show_capa_section(site_id, details)
    show_deviation_records(details["records"])


def show_capa_section(site_id, details):
    """CAPA report for the selected site: generated in memory, shown, and offered as a download."""
    st.subheader("CAPA report (Corrective and Preventive Actions)")
    inputs = (details["row"], details["warnings"], details["deviations"])
    today = date.today().isoformat()
    download_report = capa_generator.build_capa_report(*inputs, generated_on=today)
    screen_report = capa_generator.build_capa_report(*inputs, generated_on=today, for_screen=True)
    capa_needed = capa_generator.needs_capa(details["row"], details["warnings"])

    if capa_needed:
        st.caption(
            f"Rule-based suggestions drafted from {site_id}'s deviations and warnings. "
            f"{capa_generator.PROTOTYPE_NOTICE}"
        )
    else:
        st.success(capa_generator.NO_CAPA_MESSAGE, icon="✅")

    st.download_button(
        "Download CAPA report",
        data=download_report.encode("utf-8"),
        file_name=capa_generator.capa_file_name(site_id),
        mime="text/markdown",
        icon="📄",
        help="Saves the report as a Markdown (.md) file.",
    )
    with st.expander("View CAPA report", expanded=capa_needed):
        st.markdown(screen_report)


def show_deviation_records(records):
    st.subheader("Deviation records")
    if records.empty:
        st.success("No deviations detected at this site.", icon="✅")
        return
    filter_severity, filter_type = st.columns(2)
    chosen_severities = filter_severity.multiselect(
        "Filter by severity", [s for s in config.SEVERITY_LEVELS if s in set(records["Severity"])]
    )
    chosen_types = filter_type.multiselect(
        "Filter by deviation type", sorted(records["Deviation type"].unique())
    )
    shown = data.filter_records(records, chosen_severities, chosen_types)
    st.caption(f"Showing {len(shown)} of {len(records)} deviation(s), most severe first.")
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config={"Explanation": st.column_config.TextColumn("Explanation", width="large")},
    )


# ---------------------------------------------------------------------------
# How it works
# ---------------------------------------------------------------------------
def show_rules_tab():
    st.subheader("How TrialGuard works")
    st.caption("All values below are read from `src/config.py` and `src/data/protocol.json`. "
               "They are simplified prototype rules, not regulatory determinations.")

    st.markdown("**1. Severity rules**")
    admin_max = config.VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE
    minor_max = config.VISIT_MINOR_MAX_DAYS_OUTSIDE
    severity_rows = [
        {"Deviation type": deviation_type, "Severity": severity}
        for deviation_type, severity in config.SEVERITY_BY_DEVIATION_TYPE.items()
    ] + [
        {"Deviation type": f"{config.OUT_OF_WINDOW_VISIT} (1–{admin_max} days outside)", "Severity": config.ADMINISTRATIVE},
        {"Deviation type": f"{config.OUT_OF_WINDOW_VISIT} ({admin_max + 1}–{minor_max} days outside)", "Severity": config.MINOR},
        {"Deviation type": f"{config.OUT_OF_WINDOW_VISIT} (more than {minor_max} days outside)", "Severity": config.MAJOR},
    ]
    st.dataframe(severity_rows, hide_index=True)

    st.markdown("**2. Site risk score**")
    severity_points = ", ".join(f"{level} {points}" for level, points in config.SEVERITY_POINTS.items())
    bonus_points = ", ".join(f"{kind} +{points}" for kind, points in config.DEVIATION_TYPE_BONUS_POINTS.items())
    levels = " · ".join(f"{level} up to {limit}" for level, limit in config.RISK_LEVELS)
    st.markdown(
        f"- Points per deviation = severity points ({severity_points}) + type bonus ({bonus_points})\n"
        f"- +{config.REPEATED_PATTERN_BONUS_POINTS} for each deviation type seen in "
        f"{config.REPEATED_PATTERN_MIN_PATIENTS}+ different patients at the site\n"
        f"- points per patient = total points ÷ patients at the site\n"
        f"- risk score = min(100, points per patient ÷ {config.SCORE_CAP_POINTS_PER_PATIENT} × 100)\n"
        f"- Levels: {levels}"
    )

    st.markdown("**3. Early warnings** (explain the score; never change it)")
    st.markdown(
        f"- Repeated dosing errors: {config.WARNING_REPEATED_DOSING_MIN}+ at a site\n"
        f"- Repeated prohibited medications: {config.WARNING_REPEATED_PROHIBITED_MED_MIN}+ at a site\n"
        f"- Increasing trend: later visits have ≥ {config.WARNING_TREND_MULTIPLIER:g}× the deviations of "
        f"early visits and at least {config.WARNING_TREND_MIN_INCREASE} more\n"
        f"- Unusually high rate: deviations per expected visit > {config.WARNING_HIGH_RATE_MULTIPLIER:g}× "
        "the study average"
    )

    st.markdown("**4. CAPA reports**")
    st.markdown(
        "- Likely contributing issues and actions come from fixed lookup tables in "
        "`src/core/capa_generator.py`, chosen by the site's risk factors and early warnings\n"
        f"- A factor needs at least {capa_generator.MIN_RISK_SHARE_FOR_ISSUE_PCT}% of the site's risk points "
        "to count as a process issue; smaller ones are corrected individually\n"
        "- Monitoring recommendation depends on the risk level\n"
        f"- {capa_generator.PROTOTYPE_NOTICE}"
    )

    st.markdown("**5. Missed visits in uploaded data**")
    st.markdown(
        "- A record with a blank `actual_day` is always a missed visit\n"
        "- **Completed trial** (and the demo data): a protocol visit with no record is a missed visit\n"
        "- **Ongoing trial**: a visit with no record is missed only if the patient has a record for a "
        "later visit; visits after the patient's last record are not yet due"
    )


def show_data_problem(error):
    st.error("**This file could not be analysed.**  \n" + error.replace("\n", "  \n"), icon="🚫")
    st.info("Fix the file and upload it again, or switch back to the built-in demo data in the sidebar.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main():
    show_header()
    outcome, data_description = choose_data_source()

    if outcome is None:
        st.info("Upload a patient visit CSV in the sidebar, or switch back to the built-in demo data.", icon="👈")
        st.stop()

    result, error = outcome
    if error:
        show_data_problem(error)
        st.stop()

    selected_site = choose_site(result)
    st.sidebar.divider()
    st.sidebar.caption(f"TrialGuard hackathon prototype. {DISCLAIMER}")

    show_data_messages(result, data_description)
    show_study_metrics(result)

    overview_tab, site_tab, rules_tab = st.tabs(["📊 Study overview", "🔍 Site details", "📐 How it works"])
    with overview_tab:
        show_overview_tab(result, selected_site)
    with site_tab:
        show_site_details_tab(result, selected_site)
    with rules_tab:
        show_rules_tab()

    st.divider()
    st.caption(f"TrialGuard hackathon prototype · {DISCLAIMER}")


main()
