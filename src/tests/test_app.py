"""
Phase 5 tests: run the real Streamlit page headlessly with Streamlit's AppTest.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v

AppTest cannot simulate a file upload, so upload handling is tested through
utils/dashboard_data.py in test_dashboard_data.py.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
DISCLAIMER = "Demo only — uses synthetic data. Not for clinical decision-making and not FDA/EMA approved."


def all_text(elements):
    return " ".join(str(element.value) for element in elements)


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


def test_app_starts_with_header_and_disclaimer(app):
    assert app.title[0].value == "🛡️ TrialGuard"
    assert app.subheader[0].value == "Clinical Trial Risk Monitor & Protocol Deviation Detector"
    assert DISCLAIMER in all_text(app.warning)


def test_study_overview_metrics(app):
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Total Sites"] == "10"
    assert metrics["Total Patients"] == "120"
    assert metrics["Total Deviations"] == "42"
    assert metrics["🔴 High-Risk Sites"] == "1"
    assert metrics["🟠 Medium-Risk Sites"] == "1"


def test_site_selector_lists_sites_by_risk(app):
    options = app.sidebar.selectbox[0].options
    assert options[:3] == ["All Sites", "SITE-104", "SITE-107"]


def test_all_sites_view_prompts_for_a_site(app):
    assert "Choose a site in the sidebar" in all_text(app.info)


def test_site_104_view(app):
    select_site(app, "SITE-104")
    assert "SITE-104 — 🔴 HIGH risk" in all_text(app.header)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Risk Score"] == "68 / 100"
    assert metrics["Total Deviations"] == "14"
    assert metrics["Major"] == "12"
    warnings = all_text(app.warning)
    assert "Repeated dosing errors" in warnings
    assert "Repeated prohibited medications" in warnings
    assert "Increasing deviation trend" in warnings
    assert "Unusually high deviation rate" in warnings
    assert "Repeated dosing deviations and repeated prohibited medication incidents" in all_text(app.error)


def test_site_107_view(app):
    select_site(app, "SITE-107")
    assert "SITE-107 — 🟠 MEDIUM risk" in all_text(app.header)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Risk Score"] == "52 / 100"
    warnings = all_text(app.warning)
    assert "Increasing deviation trend" in warnings
    assert "Unusually high deviation rate" in warnings
    assert "Repeated dosing errors" not in warnings


def test_clean_site_view(app):
    select_site(app, "SITE-105")
    assert "SITE-105 — 🟢 LOW risk" in all_text(app.header)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Risk Score"] == "0 / 100"
    assert metrics["Total Deviations"] == "0"
    successes = all_text(app.success)
    assert "No early warnings detected for this site." in successes
    assert "No deviations detected at this site." in successes


def test_upload_mode_without_file_asks_for_upload(app):
    app.sidebar.radio[0].set_value("Upload a CSV").run()
    assert not app.exception
    assert "Upload a patient visit CSV" in all_text(app.info)
    assert len(app.metric) == 0
