"""
Phase 1 check: load the protocol and the demo dataset and print a summary.

Run from the repository folder with:
    .venv\\Scripts\\python.exe src\\check_data.py
"""

import sys

import config
from utils.data_loader import (
    DataValidationError,
    get_data_warnings,
    load_patients,
    load_protocol,
    summarize_patients,
)


def main():
    print("TrialGuard - Phase 1 data check (synthetic data only)")
    print("=" * 55)

    try:
        protocol = load_protocol()
        patients = load_patients()
    except DataValidationError as error:
        print(f"FAILED: {error}")
        return 1

    print(f"\nProtocol: {protocol['protocol_id']}")
    print(f"  Expected dose:          {protocol['expected_dose_mg']} mg")
    print(f"  Prohibited medications: {', '.join(protocol['prohibited_medications'])}")
    for visit in protocol["visits"]:
        print(f"  {visit['visit']}: day {visit['expected_day']} (+/-{visit['window_days']} days)")

    summary = summarize_patients(patients)
    print(f"\nDemo dataset: {config.DEMO_PATIENTS_PATH.name}")
    print(f"  Visit records:  {summary['total_records']}")
    print(f"  Patients:       {summary['total_patients']}")
    print(f"  Sites:          {summary['total_sites']}")
    print(f"  Visits/patient: {summary['min_visits_per_patient']} to {summary['max_visits_per_patient']}")
    print(f"  Missed-visit records (blank actual_day): {summary['missed_visit_records']}")
    print("  Patients per site:")
    for site_id, count in summary["patients_per_site"].items():
        print(f"    {site_id}: {count}")

    warnings = get_data_warnings(patients, protocol)
    print(f"\nData warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  - {warning}")

    print(f"\nValidation demo with {config.SAMPLE_INVALID_UPLOAD_PATH.name}:")
    try:
        load_patients(config.SAMPLE_INVALID_UPLOAD_PATH)
        print("  UNEXPECTED: the invalid file was accepted")
        return 1
    except DataValidationError as error:
        print("  Rejected as expected. Message shown to the user:")
        for line in str(error).splitlines():
            print(f"    {line}")

    print("\nPhase 1 data check finished OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
