"""
Phase 5-7 tests: run the real Streamlit page headlessly with Streamlit's AppTest.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v

AppTest cannot simulate a file upload or read a download button's file, so
upload handling and download content are tested through
utils/dashboard_data.py and core/capa_generator.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
DISCLAIMER = "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved."
CAPA_HEADING = "CAPA report (Corrective and Preventive Actions)"


def all_text(elements):
    return " ".join(str(element.value) for element in elements)


def metrics_of(app):
    return {metric.label: metric.value for metric in app.metric}


@pytest.fixture
def app():
    test_app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    test_app.run()
    assert not test_app.exception, test_app.exception
    return test_app


def select_site(app, site_id):
    app.sidebar.selectbox[0].select(site_id).run()
    assert not app.exception, app.exception
    return app


# ---------------------------------------------------------------------------
# Study overview
# ---------------------------------------------------------------------------
def test_app_starts_with_header_and_disclaimer(app):
    assert app.title[0].value == "🛡️ TrialGuard"
    assert app.subheader[0].value == "Clinical Trial Risk Monitor & Protocol Deviation Detector"
    assert DISCLAIMER in all_text(app.warning)
    assert "How to use" in all_text(app.markdown)


def test_demo_data_is_the_default(app):
    assert app.sidebar.radio[0].value == "Built-in synthetic demo data"
    assert "Data: Built-in synthetic demo data" in all_text(app.caption)


def test_study_overview_metrics(app):
    metrics = metrics_of(app)
    assert metrics["Sites"] == "10"
    assert metrics["Patients"] == "120"
    assert metrics["Protocol Deviations"] == "42"
    assert metrics["🔴 HIGH-Risk Sites"] == "1"
    assert metrics["🟠 MEDIUM-Risk Sites"] == "1"
    assert metrics["⚠️ Sites with Early Warnings"] == "3"


def test_demo_data_has_no_data_messages(app):
    text = all_text(app.info) + all_text(app.warning)
    assert "Data preparation" not in text
    assert "Data check" not in text
    assert "Ongoing trial" not in text


def test_site_selector_lists_sites_by_risk(app):
    options = app.sidebar.selectbox[0].options
    assert options[:3] == ["All Sites", "SITE-104", "SITE-107"]


def test_all_sites_view_prompts_for_a_site(app):
    assert "Choose a site in the sidebar" in all_text(app.info)


def test_selecting_a_site_points_to_site_details_tab(app):
    select_site(app, "SITE-104")
    assert "SITE-104** is selected. Open the **🔍 Site details** tab" in all_text(app.info)


# ---------------------------------------------------------------------------
# Site details
# ---------------------------------------------------------------------------
def test_site_104_view(app):
    select_site(app, "SITE-104")
    assert "SITE-104 — 🔴 HIGH risk" in all_text(app.header)
    metrics = metrics_of(app)
    assert metrics["Risk Score"] == "68 / 100"
    assert metrics["Risk Level"] == "🔴 HIGH"
    assert metrics["Total Deviations"] == "14"
    assert metrics["Major"] == "12"
    assert "Early warnings (4)" in [s.value for s in app.subheader]
    warnings = all_text(app.warning)
    assert "Warning 1 of 4 — Repeated dosing errors" in warnings
    assert "Repeated prohibited medications" in warnings
    assert "Increasing deviation trend" in warnings
    assert "Warning 4 of 4 — Unusually high deviation rate" in warnings
    headline = all_text(app.error)
    assert "**HIGH risk (68/100):**" in headline  # level named in text, not only by colour
    assert "Repeated dosing deviations and repeated prohibited medication incidents" in headline


def test_site_107_view(app):
    select_site(app, "SITE-107")
    assert "SITE-107 — 🟠 MEDIUM risk" in all_text(app.header)
    metrics = metrics_of(app)
    assert metrics["Risk Score"] == "52 / 100"
    assert metrics["Total Deviations"] == "15"
    assert "Early warnings (2)" in [s.value for s in app.subheader]
    warnings = all_text(app.warning)
    assert "Increasing deviation trend" in warnings
    assert "Unusually high deviation rate" in warnings
    assert "Repeated dosing errors" not in warnings
    assert "**MEDIUM risk (52/100):**" in warnings


@pytest.mark.parametrize("site_id", ["SITE-105", "SITE-110"])
def test_clean_site_view(app, site_id):
    select_site(app, site_id)
    assert f"{site_id} — 🟢 LOW risk" in all_text(app.header)
    metrics = metrics_of(app)
    assert metrics["Risk Score"] == "0 / 100"
    assert metrics["Total Deviations"] == "0"
    assert "Early warnings (0)" in [s.value for s in app.subheader]
    assert "**LOW risk (0/100):**" in all_text(app.info)
    successes = all_text(app.success)
    assert "No early warnings detected for this site." in successes
    assert "No deviations detected at this site." in successes


# ---------------------------------------------------------------------------
# CAPA section
# ---------------------------------------------------------------------------
def capa_report_text(app):
    reports = [m.value for m in app.markdown if "CAPA / Corrective Action Report" in str(m.value)]
    assert len(reports) == 1, "expected exactly one CAPA report on the page"
    return reports[0]


def download_labels(app):
    return [button.proto.label for button in app.get("download_button")]


def test_capa_section_for_site_104(app):
    select_site(app, "SITE-104")
    assert CAPA_HEADING in [s.value for s in app.subheader]
    assert "Download CAPA report" in download_labels(app)
    report = capa_report_text(app)
    assert "- **Risk score:** 68 / 100" in report
    assert "Dosing procedure or dose verification" in report
    assert "Medication eligibility/review process" in report
    assert "Verify recent dosing records." in report
    assert "Recommend prompt enhanced monitoring/review of this site." in report
    assert "Prototype recommendations, not regulatory advice." in report
    assert DISCLAIMER in report


def test_capa_report_on_screen_uses_small_headings(app):
    select_site(app, "SITE-104")
    report = capa_report_text(app)
    assert report.startswith("#### CAPA / Corrective Action Report — SITE-104")
    assert "# TrialGuard" not in report
    assert "\n### " not in report          # section headings are one level smaller on screen
    assert "\n#### Corrective actions" in report


def test_capa_section_for_site_107(app):
    select_site(app, "SITE-107")
    assert "Download CAPA report" in download_labels(app)
    report = capa_report_text(app)
    assert "- **Risk score:** 52 / 100" in report
    assert "Visit scheduling or site follow-up capacity" in report
    assert "Review visit scheduling and patient follow-up." in report
    assert "Recommend increased remote monitoring and closer follow-up." in report
    assert "Verify recent dosing records." not in report


def test_capa_section_for_clean_site_105(app):
    select_site(app, "SITE-105")
    assert CAPA_HEADING in [s.value for s in app.subheader]
    message = "No CAPA actions are currently indicated for this site based on the available demo data."
    assert message in all_text(app.success)
    assert "Download CAPA report" in download_labels(app)
    report = capa_report_text(app)
    assert message in report
    assert "Corrective actions" not in report


def test_no_capa_section_when_all_sites_selected(app):
    assert CAPA_HEADING not in [s.value for s in app.subheader]
    assert download_labels(app) == []


# ---------------------------------------------------------------------------
# Upload mode
# ---------------------------------------------------------------------------
def test_upload_mode_without_file_asks_for_upload(app):
    app.sidebar.radio[0].set_value("Upload my own CSV").run()
    assert not app.exception
    assert "Upload a patient visit CSV" in all_text(app.info)
    assert len(app.metric) == 0


def test_upload_mode_offers_trial_status_and_sample_files(app):
    app.sidebar.radio[0].set_value("Upload my own CSV").run()
    assert not app.exception
    trial_status = app.sidebar.radio[1]
    assert trial_status.label == "Trial status"
    assert trial_status.value.startswith("Completed")
    assert any(option.startswith("Ongoing") for option in trial_status.options)
    assert "Download sample invalid CSV" in download_labels(app)
    assert "Visit 1, Visit 2, Visit 3, Visit 4" in all_text(app.markdown)
