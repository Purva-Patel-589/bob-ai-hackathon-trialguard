"""
Phase 1 tests: protocol loading, patient loading, validation and the
synthetic demo dataset.

Run from the repository folder with:
    .venv\\Scripts\\python.exe -m pytest src\\tests -v
"""

import importlib.util
import io
import json

import pytest

import config
from utils.data_loader import (
    DataValidationError,
    get_data_warnings,
    load_patients,
    load_protocol,
    summarize_patients,
)

HEADER = "patient_id,site_id,visit,actual_day,dose_mg,medication\n"


def csv_file(text):
    """Make an in-memory CSV file, like a Streamlit upload."""
    return io.StringIO(text)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
def test_protocol_loads_expected_values():
    protocol = load_protocol()
    assert protocol["expected_dose_mg"] == 10
    assert protocol["prohibited_medications"] == ["DrugB", "DrugC"]
    assert [v["visit"] for v in protocol["visits"]] == ["Visit 1", "Visit 2", "Visit 3", "Visit 4"]
    assert [v["expected_day"] for v in protocol["visits"]] == [0, 14, 28, 56]
    assert [v["window_days"] for v in protocol["visits"]] == [0, 2, 3, 5]


def test_protocol_with_missing_fields_is_rejected(tmp_path):
    bad_protocol = tmp_path / "protocol.json"
    bad_protocol.write_text(json.dumps({"visits": []}), encoding="utf-8")
    with pytest.raises(DataValidationError) as error:
        load_protocol(bad_protocol)
    message = str(error.value)
    assert "expected_dose_mg" in message
    assert "prohibited_medications" in message
    assert "visits" in message


def test_protocol_with_broken_json_is_rejected(tmp_path):
    bad_protocol = tmp_path / "protocol.json"
    bad_protocol.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(DataValidationError, match="not valid JSON"):
        load_protocol(bad_protocol)


# ---------------------------------------------------------------------------
# Demo dataset
# ---------------------------------------------------------------------------
def test_demo_dataset_loads_with_required_columns():
    patients = load_patients()
    for column in config.REQUIRED_COLUMNS:
        assert column in patients.columns


def test_demo_dataset_size_matches_the_brief():
    summary = summarize_patients(load_patients())
    assert summary["total_sites"] == 10
    assert all(10 <= count <= 14 for count in summary["patients_per_site"].values())
    assert summary["max_visits_per_patient"] == 4
    assert summary["total_records"] > 450


def test_demo_dataset_has_no_data_warnings():
    assert get_data_warnings(load_patients(), load_protocol()) == []


def test_word_none_in_medication_is_kept_as_text():
    patients = load_patients()
    assert (patients["medication"] == "None").sum() > 0
    assert patients["medication"].isna().sum() == 0


def test_demo_dataset_contains_planted_problems():
    """Not deviation detection: just proves the demo data has what Phase 2 needs."""
    patients = load_patients()
    site_104 = patients[patients["site_id"] == "SITE-104"]
    site_107 = patients[patients["site_id"] == "SITE-107"]

    wrong_doses_104 = site_104["dose_mg"].notna() & (site_104["dose_mg"] != 10)
    assert wrong_doses_104.sum() >= 5
    assert site_104["medication"].str.contains("DrugB|DrugC").sum() >= 4

    assert site_107["actual_day"].isna().sum() >= 2           # blank = missed
    assert site_107["patient_id"].value_counts().min() == 3   # one record removed


def test_generator_reproduces_the_committed_dataset(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "generate_synthetic_data", config.DATA_DIR / "generate_synthetic_data.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    records, _ = generator.build_records()
    output = tmp_path / "patients.csv"
    generator.write_csv(records, output)

    committed = config.DEMO_PATIENTS_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert output.read_text(encoding="utf-8") == committed


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------
def test_sample_invalid_upload_names_the_missing_columns():
    with pytest.raises(DataValidationError) as error:
        load_patients(config.SAMPLE_INVALID_UPLOAD_PATH)
    message = str(error.value)
    assert "site_id" in message
    assert "dose_mg" in message
    assert "medication" in message


def test_empty_file_is_rejected():
    with pytest.raises(DataValidationError, match="empty"):
        load_patients(csv_file(""))


def test_headers_without_records_are_rejected():
    with pytest.raises(DataValidationError, match="no records"):
        load_patients(csv_file(HEADER))


def test_text_in_numeric_column_is_rejected_with_row_number():
    text = HEADER + "PT-1,SITE-1,Visit 1,0,10,None\nPT-1,SITE-1,Visit 2,fourteen,10,None\n"
    with pytest.raises(DataValidationError) as error:
        load_patients(csv_file(text))
    assert "actual_day" in str(error.value)
    assert "3" in str(error.value)  # header is row 1, bad record is row 3


def test_blank_patient_id_is_rejected():
    text = HEADER + ",SITE-1,Visit 1,0,10,None\n"
    with pytest.raises(DataValidationError, match="patient_id"):
        load_patients(csv_file(text))


def test_column_names_and_values_are_tidied():
    text = " Patient_ID ,SITE_ID,Visit,Actual_Day,Dose_mg,Medication\n PT-1 ,SITE-1,Visit 1, 0 ,10,None\n"
    patients = load_patients(csv_file(text))
    assert list(patients.columns) == config.REQUIRED_COLUMNS
    assert patients.loc[0, "patient_id"] == "PT-1"
    assert patients.loc[0, "actual_day"] == 0


def test_blank_day_is_allowed_for_missed_visit():
    text = HEADER + "PT-1,SITE-1,Visit 2,,,\n"
    patients = load_patients(csv_file(text))
    assert patients["actual_day"].isna().all()


def test_warnings_for_suspicious_but_usable_data():
    text = (
        HEADER
        + "PT-1,SITE-1,Visit 1,0,10,None\n"
        + "PT-1,SITE-1,Visit 1,0,10,None\n"      # duplicate
        + "PT-1,SITE-2,Visit 9,-3,10,None\n"     # other site, unknown visit, negative day
    )
    warnings = get_data_warnings(load_patients(csv_file(text)), load_protocol())
    joined = " ".join(warnings)
    assert "Visit 9" in joined
    assert "more than once" in joined
    assert "more than one site" in joined
    assert "negative" in joined
