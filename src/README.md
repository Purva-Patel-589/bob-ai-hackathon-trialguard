# TrialGuard — Source Code

> **Prototype notice:** TrialGuard is a hackathon proof-of-concept. All data is
> synthetic. Its rules are simplified and are not regulatory determinations. It
> is not clinically validated and must not be used for real clinical decisions.

## Folder layout

```
src/
├── config.py                  ← every rule, threshold and weight in one place
├── check_data.py              ← Phase 1 check: loads data and prints a summary
├── check_deviations.py        ← runs detection + severity and prints examples
├── core/
│   ├── deviation_detector.py  ← compares records with the protocol, lists deviations
│   └── severity.py            ← labels each deviation Major / Minor / Administrative
├── data/
│   ├── protocol.json          ← fictional protocol (visits, windows, dose, prohibited meds)
│   ├── patients.csv           ← synthetic demo dataset (generated, do not edit by hand)
│   ├── generate_synthetic_data.py  ← recreates patients.csv
│   └── sample_invalid_upload.csv   ← deliberately broken file for testing validation
├── utils/
│   └── data_loader.py         ← reads + validates protocol and patient CSVs
└── tests/
    ├── test_data_loader.py         ← Phase 1 tests (pytest)
    ├── test_deviation_detector.py  ← Phase 2 tests (pytest)
    └── test_severity.py            ← Phase 3 tests (pytest)
```

Coming in later phases: risk scoring, early warnings and CAPA reports in
`core/`, and `app.py` (Streamlit dashboard).

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
# Recreate the demo dataset
.venv\Scripts\python.exe src\data\generate_synthetic_data.py

# Phase 1 data check
.venv\Scripts\python.exe src\check_data.py

# Deviation detection + severity check
.venv\Scripts\python.exe src\check_deviations.py

# Automated tests
.venv\Scripts\python.exe -m pytest src\tests -v
```
