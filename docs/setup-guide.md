# Setup Guide

> **This file is read by the automated evaluation pipeline.** It gives exact steps to run
> TrialGuard locally on **Windows** using **PowerShell**.
>
> **Tested environment:** these steps were run during development on Windows 11 with
> Python 3.11.9 in an existing project folder. They have **not yet been tested on a fresh
> machine** — please report anything that does not work.

TrialGuard is a hackathon proof-of-concept that uses **synthetic data only**. It is not for
clinical decision-making and is not FDA/EMA approved.

---

## Prerequisites

- [ ] **Python 3.11** — developed and tested with 3.11.9. Other Python versions have not been
      tested. Download from <https://www.python.org/downloads/> and tick
      **"Add python.exe to PATH"** during installation.
- [ ] **Git** — <https://git-scm.com/downloads>
- [ ] **Internet access** for the one-time package installation (pandas, Streamlit, Plotly,
      pytest).
- [ ] *Optional:* **VS Code** — <https://code.visualstudio.com/>

Check your installs in PowerShell:

```powershell
python --version
```

```powershell
git --version
```

## Environment Variables

**None are required.** TrialGuard uses no API keys, passwords, databases or external services.
You do not need to create a `.env` file.

---

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/Purva-Patel-589/bob-ai-hackathon-trialguard.git
```

```powershell
cd bob-ai-hackathon-trialguard
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

This creates a private Python environment in the `.venv` folder (already excluded from Git).

### 3. Use the virtual environment — choose ONE option

**Option A (recommended): call the environment's Python directly.** No activation needed, so
PowerShell security settings cannot block it. Every command in this guide uses this form:

```powershell
.venv\Scripts\python.exe --version
```

**Option B: activate the environment** (only if your PowerShell allows running scripts):

```powershell
.venv\Scripts\Activate.ps1
```

If it works, your prompt starts with `(.venv)` and you may type `python` instead of
`.venv\Scripts\python.exe`. If you see an error saying *running scripts is disabled on this
system*, simply use **Option A** — you do not need to change any security settings.

### 4. Install the dependencies

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This installs `pandas`, `streamlit`, `plotly` and `pytest` (versions are limited in
`requirements.txt`).

---

## Verify the Installation

### Run the automated tests

```powershell
.venv\Scripts\python.exe -m pytest src\tests -v
```

Expected result: **334 passed**. The dashboard tests start the app in the background, so the
full run can take up to about a minute.

### Run the check scripts

Each script prints a readable summary and should finish with a line ending in **OK**.

```powershell
.venv\Scripts\python.exe src\check_data.py
```

```powershell
.venv\Scripts\python.exe src\check_deviations.py
```

```powershell
.venv\Scripts\python.exe src\check_risk.py
```

```powershell
.venv\Scripts\python.exe src\check_app.py
```

| Script | What it checks |
|---|---|
| `check_data.py` | Protocol and demo data load; the invalid sample file is rejected with a clear message |
| `check_deviations.py` | 42 deviations are found in the demo data, with severity |
| `check_risk.py` | Site ranking, risk levels, top risk factors and early warnings |
| `check_app.py` | The dashboard renders without errors for SITE-104, SITE-107 and SITE-105 (no browser needed) |

---

## Running the Application

```powershell
.venv\Scripts\python.exe -m streamlit run src\app.py
```

- Your browser should open automatically. If it does not, open **<http://localhost:8501>**.
- `localhost` means the app runs **only on your own computer**; nothing is published online.
- The terminal also shows a "Network URL" — you can ignore it.
- If Streamlit asks for an email address the first time, press **Enter** to skip.
- To stop the app, click the terminal and press **Ctrl+C**.

---

## Using the Built-in Demo Data

The app starts with **Built-in synthetic demo data** selected in the sidebar (10 fictional
sites, 120 fictional patients).

1. Look at the **Study overview** tab: the site risk ranking, the risk score chart, sites with
   early warnings, and deviations by type and severity.
2. In the sidebar under **2. Choose a site**, select **SITE-104**.
3. Open the **🔍 Site details** tab (you must click the tab). You should see:
   - **Risk Score 68 / 100 — HIGH**, 14 deviations,
   - **Early warnings (4)**,
   - the **CAPA report** with a **Download CAPA report** button.
4. Select **SITE-107** → **52 / 100 — MEDIUM**, with an increasing deviation trend warning.
5. Select **SITE-105** → **0 / 100 — LOW**, no warnings, and a message that no CAPA actions are
   indicated.

## Uploading Your Own CSV

1. In the sidebar, choose **Upload my own CSV**.
2. Open **CSV format, example and sample files** to see the format, or download the demo data
   or the deliberately invalid sample file to try the upload.
3. Upload a CSV with exactly these columns:

   | Column | Meaning |
   |---|---|
   | `patient_id` | Patient identifier |
   | `site_id` | Site identifier |
   | `visit` | One of `Visit 1`, `Visit 2`, `Visit 3`, `Visit 4` (from `src/data/protocol.json`) |
   | `actual_day` | Study day of the visit — **leave blank if the visit was missed** |
   | `dose_mg` | Dose in mg (number) |
   | `medication` | `None` if no other medication; separate several with `;` |

   Example:

   ```text
   patient_id,site_id,visit,actual_day,dose_mg,medication
   PT-001,SITE-A,Visit 1,0,10,None
   PT-001,SITE-A,Visit 2,15,10,DrugA
   PT-001,SITE-A,Visit 3,,,
   ```

4. If the file has a problem, the dashboard shows a red message explaining what to fix
   (for example, missing columns). Notes and warnings about the data (such as ignored visit
   names or duplicate rows) appear at the top of the page.

### Completed vs Ongoing trial status

After choosing **Upload my own CSV**, pick a **Trial status**:

| Trial status | Use it when… | A protocol visit with **no record** counts as missed… |
|---|---|---|
| **Completed** (default) | every patient has finished the whole visit schedule | always |
| **Ongoing** | some patients have not reached every visit yet | only if the patient already has a record for a **later** visit |

In **Ongoing** mode, visits after a patient's last record are treated as *not yet due* and the
page tells you how many there are. A row with a blank `actual_day` is **always** a missed visit.
The built-in demo data always uses **Completed**.

---

## Known Limitations

- Simplified, **prototype rules** — not regulatory determinations or a validated risk model.
- **Synthetic data only**; results on real trial data are unknown.
- One protocol at a time; study days rather than calendar dates; a single dose value.
- **Ongoing mode** does not flag visits that a dropped-out patient never reached (add a row with
  a blank `actual_day` to record them).
- **No login, database or audit trail** — do not deploy publicly or use with real patient data.
- **Not performance-tested** on large files.
- After selecting a site, you must click the **Site details** tab yourself.
- The app has only been run on Windows during development.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `python` is not recognized | Install Python 3.11 and tick "Add python.exe to PATH", then open a new PowerShell window. You can also try `py -3.11 -m venv .venv`. |
| `running scripts is disabled on this system` when activating | Use **Option A** (call `.venv\Scripts\python.exe` directly). No activation is needed. |
| `No module named streamlit` (or pandas / plotly / pytest) | Install into the virtual environment: `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| `.venv\Scripts\python.exe` is not found | Make sure you are in the `bob-ai-hackathon-trialguard` folder and ran `python -m venv .venv` |
| Browser does not open | Open <http://localhost:8501> manually |
| Port 8501 is already in use | Stop the other app, or run on another port: `.venv\Scripts\python.exe -m streamlit run src\app.py --server.port 8502` |
| Upload shows "missing required column(s)" | Rename your columns to exactly `patient_id, site_id, visit, actual_day, dose_mg, medication` |
| Upload shows a hint about semicolons | Save the file as a comma-separated CSV and upload again |
| Many unexpected "Missed visit" results for mid-trial data | Choose **Trial status: Ongoing** in the sidebar |
| Tests take a while | The dashboard tests run the real app headlessly; a full run can take up to about a minute |
