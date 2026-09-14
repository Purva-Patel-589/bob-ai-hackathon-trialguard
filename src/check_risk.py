"""
Phase 4 check: site risk scores, risk levels, top risk factors and early
warnings for the demo dataset.

Run from the repository folder with:
    .venv\\Scripts\\python.exe src\\check_risk.py

PROTOTYPE: simplified scoring rules on synthetic data. Not a validated risk
model and not for real clinical or regulatory decisions.
"""

import sys

import pandas as pd

import config
from core.early_warning import detect_early_warnings, summarize_site_warnings
from core.risk_scoring import RiskScoringError, run_risk_analysis
from core.severity import SeverityRuleError
from utils.data_loader import DataValidationError

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 120)

RANKING_COLUMNS = [
    "site_id", "patients", "total_deviations", "major_deviations", "minor_deviations",
    "administrative_deviations", "repeated_patterns", "total_points", "points_per_patient",
    "risk_score", "risk_level",
]


def main():
    print("TrialGuard - Phase 4 site risk + early warning check (synthetic data only)")
    print("Prototype scoring rules - not a validated risk model.")
    print("=" * 78)

    try:
        analysis = run_risk_analysis()
    except (DataValidationError, SeverityRuleError, RiskScoringError) as error:
        print(f"FAILED: {error}")
        return 1

    site_risk = analysis["site_risk"]
    warnings = detect_early_warnings(site_risk, analysis["deviations"], analysis["protocol"])
    summary = summarize_site_warnings(site_risk, warnings)

    print(
        f"\nFormula: points_per_patient = total_points / patients; "
        f"risk_score = min(100, points_per_patient / {config.SCORE_CAP_POINTS_PER_PATIENT} x 100)"
    )
    print("Levels:  " + ", ".join(
        f"{level} up to {limit}" for level, limit in config.RISK_LEVELS
    ))

    print("\nSite ranking (highest risk first):")
    ranking = site_risk[RANKING_COLUMNS].copy()
    ranking.insert(0, "rank", range(1, len(ranking) + 1))
    print(ranking.to_string(index=False))

    counts = site_risk["risk_level"].value_counts()
    print("\nSites per risk level: " + ", ".join(
        f"{level} {int(counts.get(level, 0))}" for level, _ in config.RISK_LEVELS
    ))

    print("\nTop risk factors:")
    print(site_risk[["site_id", "top_risk_factors"]].to_string(index=False))

    print(f"\nEarly warnings: {len(warnings)} across {warnings['site_id'].nunique()} site(s)")
    for site in summary.to_dict("records"):
        print(f"\n  {site['site_id']}  score {site['risk_score']}  {site['risk_level']}")
        print(f"    {site['headline']}")
        for message in warnings.loc[warnings["site_id"] == site["site_id"]].to_dict("records"):
            print(f"    - {message['warning_type']}: {message['message']}")

    print("\nPhase 4 risk check finished OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
