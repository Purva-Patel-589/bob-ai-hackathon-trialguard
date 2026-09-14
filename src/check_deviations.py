"""
Check: run deviation detection + severity classification on the demo dataset
and print the results.

Run from the repository folder with:
    .venv\\Scripts\\python.exe src\\check_deviations.py

Severity labels are simplified prototype rules, not regulatory determinations.
"""

import sys

import pandas as pd

import config
from core.deviation_detector import run_detection, summarize_deviations
from core.severity import SeverityRuleError, add_severity, summarize_severity
from utils.data_loader import DataValidationError

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 60)

SHORT_COLUMNS = ["patient_id", "visit", "deviation_type", "severity", "expected", "actual", "days_outside_window"]
EXAMPLES_PER_SEVERITY = 3


def print_site(deviations, site_id, types):
    site = deviations[deviations["site_id"] == site_id]
    counts = site["severity"].value_counts()
    severity_text = ", ".join(f"{level}: {int(counts.get(level, 0))}" for level in config.SEVERITY_LEVELS)
    print(f"\n--- {site_id}: {len(site)} deviation(s), {site['patient_id'].nunique()} patient(s) affected ---")
    print(f"Severity: {severity_text}")
    for deviation_type in types:
        rows = site[site["deviation_type"] == deviation_type]
        print(f"\n{deviation_type}: {len(rows)}")
        if not rows.empty:
            print(rows[SHORT_COLUMNS].to_string(index=False))


def main():
    print("TrialGuard - deviation detection + severity check (synthetic data only)")
    print("Severity labels are simplified prototype rules, not regulatory determinations.")
    print("=" * 76)

    try:
        deviations = add_severity(run_detection())
    except (DataValidationError, SeverityRuleError) as error:
        print(f"FAILED: {error}")
        return 1

    summary = summarize_deviations(deviations)
    severity = summarize_severity(deviations)

    print(f"\nTotal deviations:  {summary['total_deviations']}")
    print(f"Patients affected: {summary['patients_affected']}")

    print("\nBy severity:")
    for level, count in severity["by_severity"].items():
        print(f"  {level}: {count}")

    print("\nBy type:")
    for deviation_type, count in summary["by_type"].items():
        print(f"  {deviation_type}: {count}")

    print("\nBy site and severity:")
    by_site = severity["by_site"].copy()
    by_site["Total"] = by_site.sum(axis=1)
    print(by_site.to_string())

    print(f"\nExamples of each severity (up to {EXAMPLES_PER_SEVERITY}, different types first):")
    for level in config.SEVERITY_LEVELS:
        rows = deviations[deviations["severity"] == level]
        examples = pd.concat([rows.drop_duplicates("deviation_type"), rows]).drop_duplicates()
        print(f"\n  {level}:")
        for row in examples.head(EXAMPLES_PER_SEVERITY).to_dict("records"):
            print(f"    {row['patient_id']} ({row['site_id']}, {row['visit']}) - {row['deviation_type']}")
            print(f"      expected {row['expected']}; actual {row['actual']}")
            print(f"      why {level}: {row['severity_rule']}")

    print_site(deviations, "SITE-104", [config.INCORRECT_DOSE, config.PROHIBITED_MEDICATION,
                                        config.OUT_OF_WINDOW_VISIT, config.MISSING_DOCUMENTATION])
    print_site(deviations, "SITE-107", [config.OUT_OF_WINDOW_VISIT, config.MISSED_VISIT])

    print("\nDeviation + severity check finished OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
