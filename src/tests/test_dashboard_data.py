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
    assert set(demo) == {
        "protocol", "patients", "data_notes", "data_warnings", "assume_schedule_complete",
        "visits_not_yet_due", "deviations", "site_risk", "warnings", "site_summary",
    }
    assert len(demo["deviations"]) == 42
    assert "severity" in demo["deviations"].columns
    assert demo["data_warnings"] == []
    assert demo["data_notes"] == []
    assert demo["assume_schedule_complete"] is True
    assert demo["visits_not_yet_due"] == 0


@pytest.mark.parametrize(
    "site_id, score, level, deviations",
    [("SITE-104", 68, "HIGH", 14), ("SITE-107", 52, "MEDIUM", 15), ("SITE-105", 0, "LOW", 0), ("SITE-110", 0, "LOW", 0)],
)
def test_demo_key_sites_unchanged(demo, site_id, score, level, deviations):
    row = demo["site_risk"].set_index("site_id").loc[site_id]
    assert (row["risk_score"], row["risk_level"], row["total_deviations"]) == (score, level, deviations)


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
        ((HEADER + "PT-1,SITE-1,Visit 1,0,10,None,EXTRA\n").encode(), "more values than there are column headers"),
        ((HEADER + "PT-1,SITE-1,Week 1,0,10,None\n").encode(), "no visit name matches the protocol"),
        (HEADER.replace(",", ";").encode() + b"PT-1;SITE-1;Visit 1;0;10;None\n", "semicolons"),
    ],
)
def test_bad_uploads_return_errors_not_exceptions(file_bytes, expected_text):
    result, error = data.analyze_uploaded_bytes(file_bytes)
    assert result is None
    assert expected_text in error


def test_unexpected_error_is_turned_into_a_message(monkeypatch):
    def broken(patients, protocol, assume_schedule_complete=True):
        raise RuntimeError("something odd")

    monkeypatch.setattr(data, "run_analysis", broken)
    result, error = data.analyze_source(config.DEMO_PATIENTS_PATH)
    assert result is None
    assert "unexpected problem" in error
    assert "something odd" in error


def full_schedule(patient="PT-1", site="SITE-1"):
    return "".join(f"{patient},{site},Visit {n},{day},10,None\n" for n, day in [(1, 0), (2, 14), (3, 28), (4, 56)])


def test_unknown_visit_names_are_ignored_and_explained():
    text = HEADER + full_schedule() + "PT-1,SITE-1,Visit 9,5,20,DrugB\n"
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert any("Visit 9" in note and "Ignored 1 record" in note for note in result["data_notes"])
    assert result["deviations"].empty  # the Visit 9 row's wrong dose/medication is not analysed


def test_patient_with_only_unknown_visits_gets_no_false_missed_visits():
    text = HEADER + full_schedule() + "PT-2,SITE-1,Week 1,0,10,None\nPT-2,SITE-1,Week 2,14,10,None\n"
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert result["deviations"].empty
    assert data.study_metrics(result)["total_patients"] == 1


def test_visit_names_match_ignoring_capitals_and_spaces():
    text = HEADER + full_schedule().replace("Visit 2", "visit  2").replace("Visit 3", " VISIT 3 ")
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert result["deviations"].empty
    assert any("ignoring capitals and spaces" in note for note in result["data_notes"])


def test_exact_duplicate_records_are_counted_once():
    text = HEADER + full_schedule().replace("Visit 2,14,10,None", "Visit 2,14,20,None") + "PT-1,SITE-1,Visit 2,14,20,None\n"
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert len(result["deviations"]) == 1  # one wrong dose, not two
    assert any("Removed 1 exact duplicate" in note for note in result["data_notes"])
    assert result["data_warnings"] == []


def test_conflicting_duplicates_are_kept_and_warned():
    text = HEADER + full_schedule() + "PT-1,SITE-1,Visit 2,15,10,None\n"
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert any("more than once with different values" in warning for warning in result["data_warnings"])


def test_no_medication_lookalike_is_warned():
    text = HEADER + full_schedule().replace("Visit 2,14,10,None", "Visit 2,14,10,N/A")
    result, error = data.analyze_uploaded_bytes(text.encode())
    assert error is None
    assert result["deviations"].empty
    assert any("'N/A'" in warning and "look like 'no medication'" in warning for warning in result["data_warnings"])


def test_excel_utf8_and_windows_encoded_files_are_accepted():
    utf8_with_marker = ("\ufeff" + HEADER + full_schedule()).encode("utf-8")
    windows_encoded = (HEADER + full_schedule().replace("None", "Paracétamol")).encode("cp1252")
    for file_bytes in (utf8_with_marker, windows_encoded):
        result, error = data.analyze_uploaded_bytes(file_bytes)
        assert error is None
        assert data.study_metrics(result)["total_patients"] == 1


# ---------------------------------------------------------------------------
# Mid-trial uploads (trial still ongoing)
# ---------------------------------------------------------------------------
MID_TRIAL = (
    HEADER
    + full_schedule("PT-DONE")                                   # finished all visits
    + "PT-MID,SITE-1,Visit 1,0,10,None\nPT-MID,SITE-1,Visit 2,14,10,None\n"  # reached Visit 2 so far
    + "PT-GAP,SITE-1,Visit 1,0,10,None\nPT-GAP,SITE-1,Visit 3,28,10,None\n"  # skipped Visit 2
)


def test_completed_trial_counts_every_unrecorded_visit_as_missed():
    result, _ = data.analyze_uploaded_bytes(MID_TRIAL.encode(), assume_schedule_complete=True)
    missed = result["deviations"].groupby("patient_id")["visit"].apply(list).to_dict()
    assert missed == {"PT-GAP": ["Visit 2", "Visit 4"], "PT-MID": ["Visit 3", "Visit 4"]}


def test_ongoing_trial_does_not_flag_visits_not_yet_due():
    result, error = data.analyze_uploaded_bytes(MID_TRIAL.encode(), assume_schedule_complete=False)
    assert error is None
    missed = result["deviations"].groupby("patient_id")["visit"].apply(list).to_dict()
    assert missed == {"PT-GAP": ["Visit 2"]}   # a real gap before a later visit is still missed
    assert result["visits_not_yet_due"] == 3   # PT-MID Visit 3 and 4, PT-GAP Visit 4
    assert result["assume_schedule_complete"] is False


def test_demo_data_in_ongoing_mode_documents_the_trade_off():
    """
    Known trade-off: PT-107-12 has no Visit 4 record and no later visit, so in
    ongoing mode it is 'not yet due' instead of missed. The demo therefore uses
    completed mode (the default).
    """
    result, error = data.analyze_source(config.DEMO_PATIENTS_PATH, assume_schedule_complete=False)
    assert error is None
    site_107 = result["site_risk"].set_index("site_id").loc["SITE-107"]
    assert site_107["total_deviations"] == 14
    assert result["visits_not_yet_due"] == 1


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
        "Site", "Risk Level", "Risk Score", "Patients", "Deviations", "Major", "Minor", "Administrative",
    ]
    assert table["Risk Score"].is_monotonic_decreasing
    assert table.iloc[0].to_dict() == {
        "Site": "SITE-104", "Risk Level": "🔴 HIGH", "Risk Score": 68, "Patients": 12, "Deviations": 14,
        "Major": 12, "Minor": 0, "Administrative": 2,
    }
    assert table.iloc[1]["Risk Level"] == "🟠 MEDIUM"


def test_site_overview_table_with_early_warning_counts(demo):
    table = data.site_overview_table(demo["site_risk"], demo["site_summary"]).set_index("Site")
    assert table.loc["SITE-104", "Early Warnings"] == 4
    assert table.loc["SITE-107", "Early Warnings"] == 2
    assert table.loc["SITE-105", "Early Warnings"] == 0


def test_every_risk_level_label_contains_the_word(demo):
    table = data.site_overview_table(demo["site_risk"])
    for label in table["Risk Level"]:
        assert label.split()[-1] in {"HIGH", "MEDIUM", "LOW"}


def test_protocol_visit_names():
    assert data.protocol_visit_names() == ["Visit 1", "Visit 2", "Visit 3", "Visit 4"]
    assert data.protocol_visit_names("does-not-exist.json") == []


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
    for trace in figure.data:                   # level word on every bar, not only colour
        assert all(label.endswith(trace.name) for label in trace.text)
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
