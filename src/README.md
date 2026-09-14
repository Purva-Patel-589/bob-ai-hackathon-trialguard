# TrialGuard — Source Code

> **Prototype notice:** TrialGuard is a hackathon proof-of-concept. All data is
> synthetic. Its rules are simplified and are not regulatory determinations. It
> is not clinically validated and must not be used for real clinical decisions.

## Folder layout

```
src/
├── app.py                     ← Streamlit dashboard (display only, no rules)
├── config.py                  ← every rule, threshold and weight in one place
├── check_app.py               ← Phase 5 check: dashboard renders without errors (headless)
├── check_data.py              ← Phase 1 check: loads data and prints a summary
├── check_deviations.py        ← runs detection + severity and prints examples
├── check_risk.py              ← Phase 4 check: site ranking, risk factors, early warnings
├── core/
│   ├── deviation_detector.py  ← compares records with the protocol, lists deviations
│   ├── severity.py            ← labels each deviation Major / Minor / Administrative
│   ├── risk_scoring.py        ← 0-100 risk score and level for every site
│   ├── early_warning.py       ← explains why a site is (becoming) risky
│   └── capa_generator.py      ← rule-based CAPA report (Markdown) for one site
├── data/
│   ├── protocol.json          ← fictional protocol (visits, windows, dose, prohibited meds)
│   ├── patients.csv           ← synthetic demo dataset (generated, do not edit by hand)
│   ├── generate_synthetic_data.py  ← recreates patients.csv
│   └── sample_invalid_upload.csv   ← deliberately broken file for testing validation
├── utils/
│   ├── data_loader.py         ← reads + validates protocol and patient CSVs
│   ├── dashboard_data.py      ← runs every step and shapes results for the dashboard
│   └── charts.py              ← Plotly charts used by the dashboard
└── tests/
    ├── test_data_loader.py         ← Phase 1 tests (pytest)
    ├── test_deviation_detector.py  ← Phase 2 tests (pytest)
    ├── test_severity.py            ← Phase 3 tests (pytest)
    ├── test_risk_scoring.py        ← Phase 4 tests (pytest)
    ├── test_early_warning.py       ← Phase 4 tests (pytest)
    ├── test_dashboard_data.py      ← Phase 5 tests: dashboard data + charts
    ├── test_app.py                 ← Phase 5-6 tests: the real page, run headlessly
    └── test_capa_generator.py      ← Phase 6 tests: CAPA reports
```

## Dashboard

```
CSV -> data_loader -> deviation_detector -> severity -> risk_scoring
    -> early_warning -> capa_generator -> app.py (display)
                        (utils/dashboard_data.py shapes tables for the page)
```

`app.py` contains no detection, severity, scoring or warning rules. It shows:

- **Sidebar:** data source (built-in synthetic data or CSV upload) and site selector
- **Metric cards:** total sites, patients, deviations, high- and medium-risk sites
- **Study overview tab:** site risk table, risk score bar chart, sites with
  early warnings, deviations by type and severity
- **Site details tab:** score, level, counts, early warnings, top risk factors,
  risk points by factor, filterable deviation records
- **How it works tab:** the current rules, read live from `config.py`

Invalid uploads (missing columns, empty or malformed files) show a friendly
error message instead of a traceback.

## CAPA reports

> Prototype recommendations, not regulatory advice.

`core/capa_generator.py` builds a Markdown CAPA report for one site from the
already-calculated site risk row, early warnings and deviations. It does not
re-score or re-detect anything. The report contains: header, executive
summary, early warnings, detected deviations, affected patients, likely
contributing issues (rule-based hypotheses), corrective actions, preventive
actions, a monitoring recommendation and disclaimers.

All wording comes from editable tables at the top of the module:

| Table | What it controls |
|---|---|
| `ISSUE_RULES_BY_FACTOR` | Issue, corrective and preventive actions for dosing, prohibited medications, late/missed visits, missing documentation |
| `ISSUE_RULES_BY_WARNING` | Extra issue and actions for the increasing-trend and high-rate warnings |
| `MIN_RISK_SHARE_FOR_ISSUE_PCT` (10) | A factor with less than 10% of the site's risk points is listed as a smaller contributor to correct individually, not as a process issue (unless its repeated-pattern warning fired) |
| `MONITORING_BY_LEVEL` | Monitoring recommendation for HIGH / MEDIUM / LOW |

A site with no deviations and no warnings gets: *"No CAPA actions are
currently indicated for this site based on the available demo data."*

In the dashboard the report appears under **Site details → CAPA report**, with
a **Download CAPA report** button. The report is created in memory; no files
are written.

## Deviation detection rules

| Deviation type | Rule |
|---|---|
| Missed visit | Protocol visit has no record, or the record's `actual_day` is blank |
| Out-of-window visit | `actual_day` is outside `expected_day ± window_days`; days outside is recorded |
| Incorrect dose | `dose_mg` differs from the protocol's `expected_dose_mg` |
| Prohibited medication | A medication in the cell is on the protocol's prohibited list (case-insensitive; one deviation per drug) |
| Missing documentation | A visit that took place has a blank `dose_mg` or blank `medication` |

Missed visits are not checked for the other rules.

## Severity rules

> Simplified prototype rules — **not** regulatory determinations.

| Deviation type | Severity | Setting in `config.py` |
|---|---|---|
| Missed visit | Major | `SEVERITY_BY_DEVIATION_TYPE` |
| Incorrect dose | Major | `SEVERITY_BY_DEVIATION_TYPE` |
| Prohibited medication | Major | `SEVERITY_BY_DEVIATION_TYPE` |
| Missing documentation | Administrative | `SEVERITY_BY_DEVIATION_TYPE` |
| Out-of-window visit, 1–2 days outside | Administrative | `VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE = 2` |
| Out-of-window visit, 3–7 days outside | Minor | `VISIT_MINOR_MAX_DAYS_OUTSIDE = 7` |
| Out-of-window visit, more than 7 days outside | Major | |

`add_severity()` adds two columns after `deviation_type`: `severity` and
`severity_rule` (a plain-English reason, e.g. "8 day(s) outside window: more
than 7 days is Major"). If `config.py` contains an inconsistent setting, a
clear error explains what to fix.

## Site risk score

> Prototype scoring — not a validated risk model.

1. **Points per deviation** = severity points (Major 10, Minor 4,
   Administrative 1) + type bonus (Incorrect dose +5, Prohibited medication +7,
   Missed or out-of-window visit +3).
2. **Repeated-pattern bonus**: +5 for each deviation type seen in 2 or more
   different patients at the site.
3. **total_points** = step 1 + step 2.
4. **points_per_patient** = total_points ÷ patients at the site.
5. **risk_score** = min(100, points_per_patient ÷ 25 × 100), rounded to a
   whole number (`SCORE_CAP_POINTS_PER_PATIENT = 25`).
6. **risk_level**: 0–30 LOW, 31–60 MEDIUM, 61–100 HIGH.

Every point belongs to one risk factor (dosing errors, prohibited medications,
late or missed visits, missing documentation, repeated patterns). The factor
points always add up to `total_points`, and the biggest three are listed as the
site's top risk factors.

## Early warnings

Warnings explain a site's risk; they **never change the score**.

| Warning | Trigger (settings in `config.py`) |
|---|---|
| Repeated dosing errors | 2+ dosing deviations at the site |
| Repeated prohibited medications | 2+ prohibited-medication incidents |
| Increasing deviation trend | Later visits (second half of schedule) have ≥ 2× the deviations of early visits **and** at least 3 more |
| Unusually high deviation rate | Deviations per expected visit > 2× the study-wide rate |

Each site also gets a one-sentence headline built from its top risk factors
and warnings, e.g. *"Repeated dosing deviations and repeated prohibited
medication incidents are driving elevated site risk."*

## Patient CSV format

| Column | Meaning | Example |
|---|---|---|
| `patient_id` | Synthetic patient ID | `PT-104-03` |
| `site_id` | Site ID | `SITE-104` |
| `visit` | Must match a visit name in `protocol.json` | `Visit 2` |
| `actual_day` | Study day the visit happened. **Blank = missed visit** | `15` |
| `dose_mg` | Dose given, in mg | `10` |
| `medication` | Other medication(s). `None` if none; separate several with `;` | `DrugA;DrugC` |

A blank `medication` on a completed visit means "not documented", which is
different from `None`.

## Demo dataset

`patients.csv` has 10 sites (`SITE-101` to `SITE-110`), 10–14 patients per
site and up to 4 visits per patient.

- **Most sites** are mostly compliant, with a little random background noise.
- **SITE-104** has repeated dosing errors and prohibited medications.
- **SITE-107** has visit scheduling that gets worse at each visit, ending in
  missed visits.

The exact planted problems are listed in `PLANTED_ISSUES` inside
`generate_synthetic_data.py`.

## Changing the protocol or rules

- **Protocol** (visits, windows, dose, prohibited medications): edit
  `data/protocol.json`. If you change visits, re-run the generator.
- **Severity rules, score weights, warning thresholds**: edit `config.py`.

## Commands (Windows PowerShell, from the repository folder)

```powershell
# Start the dashboard (opens at http://localhost:8501; stop with Ctrl+C)
.venv\Scripts\python.exe -m streamlit run src\app.py

# Check the dashboard renders without errors (no browser needed)
.venv\Scripts\python.exe src\check_app.py

# Recreate the demo dataset
.venv\Scripts\python.exe src\data\generate_synthetic_data.py

# Phase 1 data check
.venv\Scripts\python.exe src\check_data.py

# Deviation detection + severity check
.venv\Scripts\python.exe src\check_deviations.py

# Site risk scores + early warnings
.venv\Scripts\python.exe src\check_risk.py

# Automated tests
.venv\Scripts\python.exe -m pytest src\tests -v
```
