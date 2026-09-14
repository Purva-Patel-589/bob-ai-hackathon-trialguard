"""
Phase 5 tests: dashboard data preparation and charts (no Streamlit needed).

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v
"""

import pandas as pd
import pytest

import config
from core.early_warning import HIGH_DEVIATION_RATE, INCREASING_TREND
from utils import charts
from utils import dashboard_data as data

HEADER = "patient_id,site_id,visit,actual_day,dose_mg,medication\n"


@pytest.fixture(scope="module")
def demo():
    result, error = data.analyze_source(config.DEMO_PATIENTS_PATH)
    assert error is None
    return result


# ---------------------------------------------------------------------------
# Loading and error handling (never raises)
# ---------------------------------------------------------------------------
def test_demo_analysis_contains_every_step(demo):
    assert set(demo) == {"protocol", "patients", "data_warnings", "deviations", "site_risk", "warnings", "site_summary"}
    assert len(demo["deviations"]) == 42
    assert "severity" in demo["deviations"].columns
    assert demo["data_warnings"] == []


def test_uploaded_bytes_give_same_result_as_demo_file(demo):
    result, error = data.analyze_uploaded_bytes(config.DEMO_PATIENTS_PATH.read_bytes())
    assert error is None
    pd.testing.assert_frame_equal(result["site_risk"], demo["site_risk"])


def test_sample_invalid_upload_returns_friendly_error():
    result, error = data.analyze_uploaded_bytes(config.SAMPLE_INVALID_UPLOAD_PATH.read_bytes())
    assert result is None
    assert "missing required column(s): site_id, dose_mg, medication" in error


@pytest.mark.parametrize(
    "file_bytes, expected_text",
    [
        (b"", "empty"),
        (HEADER.encode(), "no records"),
        ((HEADER + "PT-1,SITE-1,Visit 1,zero,10,None\n").encode(), "must contain numbers"),
        ((HEADER + ",SITE-1,Visit 1,0,10,None\n").encode(), "patient_id"),
        (b"\xff\xfe\x00\x81\x82 not a csv", "could not be read"),
        (b"just one line of text with no columns", "missing required column"),
    ],
)
def test_bad_uploads_return_errors_not_exceptions(file_bytes, expected_text):
    result, error = data.analyze_uploaded_bytes(file_bytes)
    assert result is None
    assert expected_text in error


def test_unexpected_error_is_turned_into_a_message(monkeypatch):
    def broken(patients, protocol):
        raise RuntimeError("something odd")

    monkeypatch.setattr(data, "run_analysis", broken)
    result, error = data.analyze_source(config.DEMO_PATIENTS_PATH)
    assert result is None
    assert "unexpected problem" in error
    assert "something odd" in error


def test_unknown_visit_names_are_reported_as_data_warnings():
    text = HEADER + "PT-1,SITE-1,Visit 1,0,10,None\nPT-1,SITE-1,Visit 9,5,10,None\n"
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert any("Visit 9" in warning for warning in result["data_warnings"])


# ---------------------------------------------------------------------------
# Study overview
# ---------------------------------------------------------------------------
def test_study_metrics(demo):
    assert data.study_metrics(demo) == {
        "total_sites": 10,
        "total_patients": 120,
        "total_deviations": 42,
        "high_risk_sites": 1,
        "medium_risk_sites": 1,
        "low_risk_sites": 8,
        "sites_with_warnings": 3,
    }


def test_site_overview_table(demo):
    table = data.site_overview_table(demo["site_risk"])
    assert list(table.columns) == [
        "Site", "Patients", "Deviations", "Major", "Minor", "Administrative", "Risk Score", "Risk Level",
    ]
    assert table["Risk Score"].is_monotonic_decreasing
    assert table.iloc[0].to_dict() == {
        "Site": "SITE-104", "Patients": 12, "Deviations": 14, "Major": 12, "Minor": 0,
        "Administrative": 2, "Risk Score": 68, "Risk Level": "🔴 HIGH",
    }
    assert table.iloc[1]["Risk Level"] == "🟠 MEDIUM"


@pytest.mark.parametrize("level, label", [("HIGH", "🔴 HIGH"), ("MEDIUM", "🟠 MEDIUM"), ("LOW", "🟢 LOW")])
def test_level_label_always_includes_the_word(level, label):
    assert data.level_label(level) == label


def test_site_options_start_with_all_sites_then_risk_order(demo):
    options = data.site_options(demo["site_risk"])
    assert options[:3] == [data.ALL_SITES, "SITE-104", "SITE-107"]
    assert len(options) == 11


def test_count_by_keeps_zero_categories(demo):
    counts = data.count_by(demo["deviations"], "severity", config.SEVERITY_LEVELS)
    assert counts.to_dict("list") == {"severity": ["Major", "Minor", "Administrative"], "count": [23, 8, 11]}
    empty = data.count_by(demo["deviations"].iloc[0:0], "severity", config.SEVERITY_LEVELS)
    assert empty["count"].tolist() == [0, 0, 0]


# ---------------------------------------------------------------------------
# Site details
# ---------------------------------------------------------------------------
def test_site_104_details(demo):
    details = data.site_details(demo, "SITE-104")
    row = details["row"]
    assert (row["risk_score"], row["risk_level"], row["total_deviations"]) == (68, "HIGH", 14)
    assert details["affected_patients"] == 11
    assert len(details["warnings"]) == 4
    assert [item["factor"] for item in details["top_factors"]][:2] == ["Dosing errors", "Prohibited medications"]
    breakdown = details["breakdown"].set_index("Risk factor")
    assert breakdown.loc["Dosing errors", "Deviations"] == 7
    assert breakdown.loc["Prohibited medications", "Deviations"] == 5
    assert breakdown["Risk points"].sum() == row["total_points"] == 205
    assert len(details["records"]) == 14
    assert details["records"]["Severity"].iloc[0] == "Major"  # most severe first


def test_site_107_details(demo):
    details = data.site_details(demo, "SITE-107")
    assert (details["row"]["risk_score"], details["row"]["risk_level"]) == (52, "MEDIUM")
    assert set(details["warnings"]["warning_type"]) == {INCREASING_TREND, HIGH_DEVIATION_RATE}
    assert details["breakdown"].set_index("Risk factor").loc["Late or missed visits", "Deviations"] == 15


def test_clean_site_details(demo):
    details = data.site_details(demo, "SITE-105")
    assert details["row"]["risk_score"] == 0
    assert details["warnings"].empty
    assert details["top_factors"] == []
    assert details["records"].empty
    assert details["affected_patients"] == 0
    assert details["headline"] == "No deviations detected; no early warning signals."


def test_unknown_site_raises_key_error(demo):
    with pytest.raises(KeyError):
        data.site_details(demo, "SITE-999")


def test_repeated_patterns_row_has_points_but_no_deviation_count(demo):
    breakdown = data.site_details(demo, "SITE-104")["breakdown"].set_index("Risk factor")
    assert pd.isna(breakdown.loc["Repeated patterns", "Deviations"])
    assert breakdown.loc["Repeated patterns", "Risk points"] == 10


def test_filter_records(demo):
    records = data.site_details(demo, "SITE-104")["records"]
    assert len(data.filter_records(records)) == 14
    assert len(data.filter_records(records, severities=["Major"])) == 12
    assert len(data.filter_records(records, deviation_types=["Incorrect dose"])) == 7
    assert len(data.filter_records(records, ["Administrative"], ["Incorrect dose"])) == 0


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def test_site_risk_chart_orders_highest_at_top_and_colours_by_level(demo):
    figure = charts.site_risk_chart(demo["site_risk"])
    category_order = list(figure.layout.yaxis.categoryarray)
    assert category_order[-1] == "SITE-104"   # last category is drawn at the top
    assert category_order[-2] == "SITE-107"
    colours = {trace.name: trace.marker.color for trace in figure.data}
    assert colours == {
        "HIGH": charts.RISK_LEVEL_COLORS["HIGH"],
        "MEDIUM": charts.RISK_LEVEL_COLORS["MEDIUM"],
        "LOW": charts.RISK_LEVEL_COLORS["LOW"],
    }
    assert [trace.name for trace in figure.data] == ["HIGH", "MEDIUM", "LOW"]  # legend order
    assert sum(len(trace.y) for trace in figure.data) == 10
    assert [shape.x0 for shape in figure.layout.shapes] == [30, 60]


def test_site_risk_chart_fades_other_sites_when_one_is_selected(demo):
    figure = charts.site_risk_chart(demo["site_risk"], selected_site="SITE-107")
    for trace in figure.data:
        for site_id, opacity in zip(trace.y, trace.marker.opacity):
            assert opacity == (1.0 if site_id == "SITE-107" else 0.3)


def test_risk_factor_chart_uses_phase_4_points(demo):
    breakdown = data.site_details(demo, "SITE-104")["breakdown"]
    figure = charts.risk_factor_chart(breakdown)
    points_by_factor = dict(zip(figure.data[0].y, figure.data[0].x))
    assert points_by_factor["Dosing errors"] == 105
    assert points_by_factor["Prohibited medications"] == 85


def test_count_chart_handles_all_zero_values():
    figure = charts.horizontal_count_chart(["A", "B"], [0, 0], "Deviations")
    assert list(figure.layout.xaxis.range) == [0, 1.15]
