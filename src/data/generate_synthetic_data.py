"""
Generate the synthetic TrialGuard demo dataset: src/data/patients.csv

ALL DATA PRODUCED HERE IS FICTIONAL. Patient IDs, site IDs and drug names are
invented. Nothing is based on real patients.

How the dataset is built
------------------------
1. Every patient at every site gets one record per protocol visit, on time,
   with the correct dose. (A fully compliant baseline.)
2. Most sites then get a small amount of random "background noise" — the odd
   slightly late visit or documentation slip — because real sites are rarely
   perfect.
3. Two sites get deliberately planted problems (see PLANTED_ISSUES below):
     SITE-104  repeated dosing errors and prohibited medications
     SITE-107  visit scheduling that gets worse over time, ending in missed visits

A fixed random seed means running this script again produces exactly the
same file.

Run it from the repository folder with:
    .venv\\Scripts\\python.exe src\\data\\generate_synthetic_data.py
"""

import csv
import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
PROTOCOL_PATH = DATA_DIR / "protocol.json"
OUTPUT_PATH = DATA_DIR / "patients.csv"

RANDOM_SEED = 42

COLUMNS = ["patient_id", "site_id", "visit", "actual_day", "dose_mg", "medication"]

# Number of patients enrolled at each site
SITE_PATIENT_COUNTS = {
    "SITE-101": 12,
    "SITE-102": 11,
    "SITE-103": 13,
    "SITE-104": 12,
    "SITE-105": 12,
    "SITE-106": 10,
    "SITE-107": 12,
    "SITE-108": 14,
    "SITE-109": 12,
    "SITE-110": 12,
}

# Fictional medications that the protocol allows
ALLOWED_MEDICATIONS = ["DrugA", "DrugD", "DrugE"]
CHANCE_OF_ALLOWED_MEDICATION = 0.25

# Sites that get planted problems instead of random background noise
PROBLEM_SITES = {"SITE-104", "SITE-107"}

# Background noise at the other sites: chance per visit record
CHANCE_SLIGHTLY_LATE = 0.025      # 1-2 days outside the window
CHANCE_MODERATELY_LATE = 0.010    # 3-5 days outside the window
CHANCE_WRONG_DOSE = 0.006
CHANCE_BLANK_MEDICATION = 0.006   # medication not documented
CHANCE_PROHIBITED_MEDICATION = 0.003

# ---------------------------------------------------------------------------
# Deliberately planted problems.
# Each entry changes one visit record. Fields not listed keep their normal
# value. "missed": True blanks the visit; "remove_record": True deletes it.
# ---------------------------------------------------------------------------
PLANTED_ISSUES = [
    # --- SITE-104: repeated dosing errors (expected dose is 10 mg) ---------
    {"patient_id": "PT-104-02", "visit": "Visit 2", "dose_mg": 20},
    {"patient_id": "PT-104-02", "visit": "Visit 3", "dose_mg": 20},
    {"patient_id": "PT-104-05", "visit": "Visit 3", "dose_mg": 5},
    {"patient_id": "PT-104-07", "visit": "Visit 3", "dose_mg": 20},
    {"patient_id": "PT-104-09", "visit": "Visit 4", "dose_mg": 15},
    {"patient_id": "PT-104-11", "visit": "Visit 4", "dose_mg": 20},
    {"patient_id": "PT-104-04", "visit": "Visit 4", "dose_mg": 20},
    # --- SITE-104: prohibited medications (DrugB, DrugC) --------------------
    {"patient_id": "PT-104-03", "visit": "Visit 2", "medication": "DrugB"},
    {"patient_id": "PT-104-03", "visit": "Visit 3", "medication": "DrugA;DrugB"},
    {"patient_id": "PT-104-06", "visit": "Visit 3", "medication": "DrugC"},
    {"patient_id": "PT-104-10", "visit": "Visit 4", "medication": "DrugC"},
    {"patient_id": "PT-104-12", "visit": "Visit 4", "medication": "DrugB"},
    # --- SITE-104: smaller issues --------------------------------------------
    {"patient_id": "PT-104-08", "visit": "Visit 4", "medication": ""},
    {"patient_id": "PT-104-12", "visit": "Visit 2", "actual_day": 18},

    # --- SITE-107: scheduling slips, getting worse at each visit ------------
    # Visit 2 (day 14, +/-2): slightly late
    {"patient_id": "PT-107-01", "visit": "Visit 2", "actual_day": 17},
    {"patient_id": "PT-107-04", "visit": "Visit 2", "actual_day": 18},
    # Visit 3 (day 28, +/-3): several days outside the window
    {"patient_id": "PT-107-02", "visit": "Visit 3", "actual_day": 35},
    {"patient_id": "PT-107-05", "visit": "Visit 3", "actual_day": 36},
    {"patient_id": "PT-107-08", "visit": "Visit 3", "actual_day": 37},
    {"patient_id": "PT-107-10", "visit": "Visit 3", "actual_day": 21},
    # Visit 4 (day 56, +/-5): well outside the window, plus missed visits
    {"patient_id": "PT-107-01", "visit": "Visit 4", "actual_day": 72},
    {"patient_id": "PT-107-03", "visit": "Visit 4", "actual_day": 70},
    {"patient_id": "PT-107-04", "visit": "Visit 4", "actual_day": 71},
    {"patient_id": "PT-107-06", "visit": "Visit 4", "actual_day": 68},
    {"patient_id": "PT-107-07", "visit": "Visit 4", "actual_day": 69},
    {"patient_id": "PT-107-09", "visit": "Visit 4", "actual_day": 74},
    {"patient_id": "PT-107-02", "visit": "Visit 4", "missed": True},
    {"patient_id": "PT-107-11", "visit": "Visit 4", "missed": True},
    {"patient_id": "PT-107-12", "visit": "Visit 4", "remove_record": True},
]


def load_protocol():
    with open(PROTOCOL_PATH, encoding="utf-8") as file:
        return json.load(file)


def make_patient_id(site_id, patient_number):
    """SITE-104 + 3 -> PT-104-03"""
    site_number = site_id.split("-")[1]
    return f"PT-{site_number}-{patient_number:02d}"


def build_baseline_records(protocol, rng):
    """One compliant record per patient per visit."""
    records = []
    for site_id, patient_count in SITE_PATIENT_COUNTS.items():
        for patient_number in range(1, patient_count + 1):
            patient_id = make_patient_id(site_id, patient_number)
            for visit in protocol["visits"]:
                window = visit["window_days"]
                if rng.random() < CHANCE_OF_ALLOWED_MEDICATION:
                    medication = rng.choice(ALLOWED_MEDICATIONS)
                else:
                    medication = "None"
                records.append({
                    "patient_id": patient_id,
                    "site_id": site_id,
                    "visit": visit["visit"],
                    "actual_day": visit["expected_day"] + rng.randint(-window, window),
                    "dose_mg": protocol["expected_dose_mg"],
                    "medication": medication,
                })
    return records


def add_background_noise(records, protocol, rng):
    """Add occasional small issues at the sites that are not problem sites."""
    visits_by_name = {visit["visit"]: visit for visit in protocol["visits"]}
    noise_log = []

    for record in records:
        if record["site_id"] in PROBLEM_SITES:
            continue
        visit = visits_by_name[record["visit"]]
        latest_allowed_day = visit["expected_day"] + visit["window_days"]
        roll = rng.random()

        threshold = CHANCE_SLIGHTLY_LATE
        if roll < threshold:
            record["actual_day"] = latest_allowed_day + rng.randint(1, 2)
            noise_log.append("slightly late visit")
            continue
        threshold += CHANCE_MODERATELY_LATE
        if roll < threshold:
            record["actual_day"] = latest_allowed_day + rng.randint(3, 5)
            noise_log.append("moderately late visit")
            continue
        threshold += CHANCE_WRONG_DOSE
        if roll < threshold:
            record["dose_mg"] = rng.choice([5, 20])
            noise_log.append("wrong dose")
            continue
        threshold += CHANCE_BLANK_MEDICATION
        if roll < threshold:
            record["medication"] = ""
            noise_log.append("medication not documented")
            continue
        threshold += CHANCE_PROHIBITED_MEDICATION
        if roll < threshold:
            record["medication"] = rng.choice(protocol["prohibited_medications"])
            noise_log.append("prohibited medication")

    return noise_log


def apply_planted_issues(records):
    """Apply PLANTED_ISSUES. Returns the updated list of records."""
    records_by_key = {(r["patient_id"], r["visit"]): r for r in records}
    keys_to_remove = set()

    for issue in PLANTED_ISSUES:
        key = (issue["patient_id"], issue["visit"])
        if key not in records_by_key:
            raise ValueError(f"Planted issue refers to an unknown record: {key}")
        record = records_by_key[key]

        if issue.get("remove_record"):
            keys_to_remove.add(key)
        elif issue.get("missed"):
            record["actual_day"] = ""
            record["dose_mg"] = ""
            record["medication"] = ""
        else:
            for field in ("actual_day", "dose_mg", "medication"):
                if field in issue:
                    record[field] = issue[field]

    return [r for r in records if (r["patient_id"], r["visit"]) not in keys_to_remove]


def build_records():
    """Build the full synthetic dataset. Returns (records, background_noise_log)."""
    rng = random.Random(RANDOM_SEED)
    protocol = load_protocol()
    records = build_baseline_records(protocol, rng)
    noise_log = add_background_noise(records, protocol, rng)
    records = apply_planted_issues(records)
    return records, noise_log


def write_csv(records, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def main():
    records, noise_log = build_records()
    write_csv(records, OUTPUT_PATH)

    patient_count = len({r["patient_id"] for r in records})
    print(f"Wrote {len(records)} synthetic visit records to {OUTPUT_PATH}")
    print(f"  Sites:    {len(SITE_PATIENT_COUNTS)}")
    print(f"  Patients: {patient_count}")
    print(f"  Planted issues at {', '.join(sorted(PROBLEM_SITES))}: {len(PLANTED_ISSUES)}")
    print(f"  Background noise at other sites: {len(noise_log)}")
    for kind in sorted(set(noise_log)):
        print(f"    - {kind}: {noise_log.count(kind)}")


if __name__ == "__main__":
    main()
