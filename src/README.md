# TrialGuard — Source Code

> **Prototype notice:** TrialGuard is a hackathon proof-of-concept. All data is
> synthetic. Its rules are simplified and are not regulatory determinations. It
> is not clinically validated and must not be used for real clinical decisions.

## Folder layout

```
src/
├── config.py                  ← every rule, threshold and weight in one place
├── check_data.py              ← Phase 1 check: loads data and prints a summary
├── data/
│   ├── protocol.json          ← fictional protocol (visits, windows, dose, prohibited meds)
│   ├── patients.csv           ← synthetic demo dataset (generated, do not edit by hand)
│   ├── generate_synthetic_data.py  ← recreates patients.csv
│   └── sample_invalid_upload.csv   ← deliberately broken file for testing validation
├── utils/
│   └── data_loader.py         ← reads + validates protocol and patient CSVs
└── tests/
    └── test_data_loader.py    ← automated tests (pytest)
```

Coming in later phases: `core/` (deviation detection, severity, risk scoring,
early warnings, CAPA reports) and `app.py` (Streamlit dashboard).

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

# Automated tests
.venv\Scripts\python.exe -m pytest src\tests -v
```
