"""
TrialGuard - Streamlit dashboard.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m streamlit run src\\app.py

This file only draws the page. All rules live in src/core/ and all data
preparation lives in src/utils/dashboard_data.py:

    CSV -> data_loader -> deviation_detector -> severity -> risk_scoring
        -> early_warning -> dashboard_data -> this page

PROTOTYPE: synthetic data, simplified rules. Not for clinical decision-making.
"""

import streamlit as st

import config
from utils import charts
from utils import dashboard_data as data

st.set_page_config(page_title="TrialGuard", page_icon="🛡️", layout="wide")

DISCLAIMER = (
    "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved."
)
DEMO_SOURCE = "Use built-in synthetic demo data"
UPLOAD_SOURCE = "Upload a CSV"


# ---------------------------------------------------------------------------
# Cached analysis (re-runs only when the data changes)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Analysing synthetic demo data...")
def analyse_demo_data():
    return data.analyze_source(config.DEMO_PATIENTS_PATH)


@st.cache_data(show_spinner="Analysing uploaded file...")
def analyse_uploaded_file(file_bytes):
    return data.analyze_uploaded_bytes(file_bytes)


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------
def show_header():
    st.title("🛡️ TrialGuard")
    st.subheader("Clinical Trial Risk Monitor & Protocol Deviation Detector")
    st.markdown(
        "A proof-of-concept that compares patient visit records against a trial protocol, "
        "detects protocol deviations, scores every site's risk from 0 to 100, and raises "
        "early warnings so monitors can see **which sites need attention first**."
    )
    st.warning(DISCLAIMER, icon="⚠️")


def choose_data_source():
    """Sidebar data choice. Returns (analysis outcome or None, description of the data)."""
    st.sidebar.header("1. Data source")
    source = st.sidebar.radio("Data source", [DEMO_SOURCE, UPLOAD_SOURCE], label_visibility="collapsed")

    if source == DEMO_SOURCE:
        return analyse_demo_data(), "Built-in synthetic demo data"

    uploaded = st.sidebar.file_uploader("Patient visit records (CSV)", type=["csv"])
    with st.sidebar.expander("CSV format and sample files"):
        st.markdown("Required columns:\n" + "\n".join(f"- `{column}`" for column in config.REQUIRED_COLUMNS))
        st.caption(
            "Leave `actual_day` blank for a missed visit. Use `None` in `medication` when the "
            "patient takes nothing else. TrialGuard assumes every patient has reached the end "
            "of the visit schedule."
        )
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

    if uploaded is None:
        return None, None
    return analyse_uploaded_file(uploaded.getvalue()), f"Uploaded file: {uploaded.name}"


def show_study_overview(result):
    metrics = data.study_metrics(result)
    columns = st.columns(5)
    columns[0].metric("Total Sites", metrics["total_sites"])
    columns[1].metric("Total Patients", metrics["total_patients"])
    columns[2].metric("Total Deviations", metrics["total_deviations"])
    columns[3].metric("🔴 High-Risk Sites", metrics["high_risk_sites"])
    columns[4].metric("🟠 Medium-Risk Sites", metrics["medium_risk_sites"])


def show_overview_tab(result, selected_site):
    site_risk = result["site_risk"]

    st.subheader("Site risk overview")
    st.caption("Sites are sorted from highest to lowest risk score. 0–30 LOW · 31–60 MEDIUM · 61–100 HIGH.")
    st.dataframe(
        data.site_overview_table(site_risk),
        hide_index=True,
        width="stretch",
        column_config={
            "Risk Score": st.column_config.ProgressColumn(
                "Risk Score", min_value=0, max_value=100, format="%d"
            ),
        },
    )
    st.markdown("**Site risk scores**")
    highlight = None if selected_site == data.ALL_SITES else selected_site
    st.plotly_chart(charts.site_risk_chart(site_risk, highlight), width="stretch")

    st.subheader("Sites with early warnings")
    flagged = result["site_summary"][result["site_summary"]["warning_count"] > 0]
    if flagged.empty:
        st.success("No early warnings detected at any site.")
    else:
        st.dataframe(
            flagged.assign(risk_level=flagged["risk_level"].map(data.level_label))[
                ["site_id", "risk_score", "risk_level", "warning_count", "headline"]
            ].rename(columns={
                "site_id": "Site", "risk_score": "Risk Score", "risk_level": "Risk Level",
                "warning_count": "Warnings", "headline": "Why",
            }),
            hide_index=True,
            width="stretch",
            column_config={"Why": st.column_config.TextColumn("Why", width="large")},
        )

    st.subheader("Deviations across the study")
    deviations = result["deviations"]
    if deviations.empty:
        st.success("No protocol deviations detected in this dataset.")
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
        st.markdown("**By severity**")
        by_severity = data.count_by(deviations, "severity", config.SEVERITY_LEVELS)
        st.plotly_chart(
            charts.horizontal_count_chart(by_severity["severity"], by_severity["count"], "Deviations"),
            width="stretch",
        )


def show_site_details_tab(result, site_id):
    if site_id == data.ALL_SITES:
        st.info("👈 Choose a site in the sidebar (**2. Site**) to see its risk score, early warnings and deviations.")
        return

    details = data.site_details(result, site_id)
    row = details["row"]
    level = row["risk_level"]

    st.header(f"{site_id} — {data.level_label(level)} risk")
    headline_box = {"HIGH": st.error, "MEDIUM": st.warning}.get(level, st.success)
    headline_box(details["headline"])

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

    st.subheader("Early warnings")
    if details["warnings"].empty:
        st.success("No early warnings detected for this site.", icon="✅")
    else:
        for warning in details["warnings"].to_dict("records"):
            st.warning(f"**{warning['warning_type']}** — {warning['message']}", icon="⚠️")

    st.subheader("What is driving this site's risk")
    if not details["top_factors"]:
        st.success("This site has no risk points: no deviations were detected.")
    else:
        factor_column, table_column = st.columns([1, 1])
        with factor_column:
            st.markdown("**Top contributing factors**")
            st.markdown("\n".join(
                f"{number}. **{item['factor']}** — {item['points']} risk "
                f"{'point' if item['points'] == 1 else 'points'} ({item['share_pct']}% of the total)"
                for number, item in enumerate(details["top_factors"], start=1)
            ))
            st.dataframe(details["breakdown"], hide_index=True, width="stretch")
        with table_column:
            st.markdown("**Risk points by factor**")
            st.plotly_chart(charts.risk_factor_chart(details["breakdown"]), width="stretch")

    st.subheader("Deviation records")
    records = details["records"]
    if records.empty:
        st.success("No deviations detected at this site.")
        return
    filter_severity, filter_type = st.columns(2)
    chosen_severities = filter_severity.multiselect(
        "Filter by severity", [s for s in config.SEVERITY_LEVELS if s in set(records["Severity"])]
    )
    chosen_types = filter_type.multiselect(
        "Filter by deviation type", sorted(records["Deviation type"].unique())
    )
    shown = data.filter_records(records, chosen_severities, chosen_types)
    st.caption(f"Showing {len(shown)} of {len(records)} deviation(s).")
    st.dataframe(shown, hide_index=True, width="stretch")


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
        st.info("👈 Upload a patient visit CSV in the sidebar, or switch back to the built-in demo data.")
        st.stop()

    result, error = outcome
    if error:
        show_data_problem(error)
        st.stop()

    st.sidebar.header("2. Site")
    selected_site = st.sidebar.selectbox("Site", data.site_options(result["site_risk"]))
    st.sidebar.caption("Sites are listed from highest to lowest risk.")

    st.caption(f"Data: {data_description} · Protocol: {result['protocol'].get('protocol_id', 'unnamed')}")
    for warning in result["data_warnings"]:
        st.warning(f"Data check: {warning}")

    show_study_overview(result)

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
