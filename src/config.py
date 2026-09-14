"""
TrialGuard configuration.

Every rule, threshold and weight used by TrialGuard lives in this one file so
that it is easy to find, read and change.

PROTOTYPE NOTICE
----------------
These are simplified hackathon rules. They are NOT regulatory determinations,
they are NOT clinically validated, and TrialGuard must NOT be used for real
clinical decision-making. All data used with this prototype is synthetic.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# File locations (built from this file's location, so they work no matter
# which folder you run Python from)
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent
DATA_DIR = SRC_DIR / "data"

PROTOCOL_PATH = DATA_DIR / "protocol.json"
DEMO_PATIENTS_PATH = DATA_DIR / "patients.csv"
SAMPLE_INVALID_UPLOAD_PATH = DATA_DIR / "sample_invalid_upload.csv"

# ---------------------------------------------------------------------------
# Patient record format (used by utils/data_loader.py)
# ---------------------------------------------------------------------------
# Every uploaded CSV must contain these columns.
REQUIRED_COLUMNS = [
    "patient_id",   # e.g. PT-104-03
    "site_id",      # e.g. SITE-104
    "visit",        # must match a visit name in protocol.json, e.g. "Visit 2"
    "actual_day",   # study day the visit happened; leave blank if missed
    "dose_mg",      # dose given at the visit, in mg
    "medication",   # concomitant medication(s); "None" if none,
                    # several medications separated by ";"
]

# Columns that must contain numbers (blank is allowed, e.g. for a missed visit)
NUMERIC_COLUMNS = ["actual_day", "dose_mg"]

# Text written in the medication column when the patient takes nothing else
NO_MEDICATION_VALUE = "None"

# Separator for multiple medications in one cell, e.g. "DrugA;DrugC"
MEDICATION_SEPARATOR = ";"

# ---------------------------------------------------------------------------
# Severity rules (used from Phase 3)
# Simplified prototype rules — not regulatory determinations.
# ---------------------------------------------------------------------------
MAJOR = "Major"
MINOR = "Minor"
ADMINISTRATIVE = "Administrative"

# How many days OUTSIDE the allowed window a visit can be before it becomes
# more serious. Example with the defaults below:
#   1-2 days outside the window  -> Administrative
#   3-7 days outside the window  -> Minor
#   8+  days outside the window  -> Major
VISIT_ADMINISTRATIVE_MAX_DAYS_OUTSIDE = 2
VISIT_MINOR_MAX_DAYS_OUTSIDE = 7

SEVERITY_BY_DEVIATION_TYPE = {
    "Missed visit": MAJOR,
    "Incorrect dose": MAJOR,
    "Prohibited medication": MAJOR,
    "Missing documentation": ADMINISTRATIVE,
    # "Out-of-window visit" is decided by the day thresholds above.
}

# ---------------------------------------------------------------------------
# Site risk score weights (used from Phase 4)
# ---------------------------------------------------------------------------
SEVERITY_POINTS = {
    MAJOR: 10,
    MINOR: 4,
    ADMINISTRATIVE: 1,
}

# Extra points added on top of the severity points for certain types
DEVIATION_TYPE_BONUS_POINTS = {
    "Incorrect dose": 5,
    "Prohibited medication": 7,
    "Missed visit": 3,
    "Out-of-window visit": 3,
}

# +5 points for each deviation type seen in at least this many different
# patients at the same site
REPEATED_PATTERN_BONUS_POINTS = 5
REPEATED_PATTERN_MIN_PATIENTS = 2

# A site averaging this many points per patient gets a score of 100.
# The cap is fixed on purpose: scores are NOT relative to other sites.
SCORE_CAP_POINTS_PER_PATIENT = 25

# Risk levels: (level name, highest score in that level)
RISK_LEVELS = [
    ("LOW", 30),
    ("MEDIUM", 60),
    ("HIGH", 100),
]

# ---------------------------------------------------------------------------
# Early warning thresholds (used from Phase 4)
# ---------------------------------------------------------------------------
WARNING_REPEATED_DOSING_MIN = 2          # dosing errors at one site
WARNING_REPEATED_PROHIBITED_MED_MIN = 2  # prohibited-medication incidents
WARNING_HIGH_RATE_MULTIPLIER = 2.0       # site rate vs. study-average rate
