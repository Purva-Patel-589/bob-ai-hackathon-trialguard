"""
Phase 2 check: run deviation detection on the demo dataset and print results.

Run from the repository folder with:
    .venv\\Scripts\\python.exe src\\check_deviations.py

Severity (Major / Minor / Administrative) is NOT assigned yet - that is Phase 3.
"""

import sys

import pandas as pd

import config
from core.deviation_detector import run_detection, summarize_deviations
from utils.data_loader import DataValidationError

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 60)

SHORT_COLUMNS = ["patient_id", "visit", "deviation_type", "expected", "actual", "days_outside_window"]


def print_site(deviations, site_id, types):
    site = deviations[deviations["site_id"] == site_id]
    print(f"\n--- {site_id}: {len(site)} deviation(s), {site['patient_id'].nunique()} patient(s) affected ---")
    for deviation_type in types:
        rows = site[site["deviation_type"] == deviation_type]
        print(f"\n{deviation_type}: {len(rows)}")
        if not rows.empty:
            print(rows[SHORT_COLUMNS].to_string(index=False))


def main():
    print("TrialGuard - Phase 2 deviation detection check (synthetic data only)")
    print("=" * 68)

    try:
        deviations = run_detection()
    except DataValidationError as error:
        print(f"FAILED: {error}")
        return 1

    summary = summarize_deviations(deviations)
    print(f"\nTotal deviations:  {summary['total_deviations']}")
    print(f"Patients affected: {summary['patients_affected']}")
    print("\nBy type:")
    for deviation_type, count in summary["by_type"].items():
        print(f"  {deviation_type}: {count}")
    print("\nBy site:")
    for site_id, count in summary["by_site"].items():
        print(f"  {site_id}: {count}")

    print("\nOne example of each deviation type:")
    examples = deviations.groupby("deviation_type", sort=False).head(1)
    for row in examples.to_dict("records"):
        print(f"\n  [{row['deviation_type']}] {row['patient_id']} at {row['site_id']}, {row['visit']}")
        print(f"    expected:    {row['expected']}")
        print(f"    actual:      {row['actual']}")
        print(f"    explanation: {row['explanation']}")

    print_site(deviations, "SITE-104", [config.INCORRECT_DOSE, config.PROHIBITED_MEDICATION])
    print_site(deviations, "SITE-107", [config.OUT_OF_WINDOW_VISIT, config.MISSED_VISIT])

    print("\nPhase 2 deviation check finished OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
