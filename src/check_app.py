"""
Phase 5 check: confirm the Streamlit dashboard imports and renders without
errors, using Streamlit's headless AppTest (no browser needed).

Run from the repository folder with:
    .venv\\Scripts\\python.exe src\\check_app.py

To open the real dashboard instead:
    .venv\\Scripts\\python.exe -m streamlit run src\\app.py
"""

import logging
import sys
from pathlib import Path

APP_PATH = Path(__file__).resolve().parent / "app.py"
SITES_TO_CHECK = ["SITE-104", "SITE-107", "SITE-105"]


def main():
    print("TrialGuard - Phase 5 dashboard check (headless)")
    print("=" * 48)

    try:
        import plotly
        import streamlit
        from streamlit.testing.v1 import AppTest
    except ImportError as error:
        print(f"FAILED: a dashboard package is not installed ({error}).")
        print("Install with: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    # Hide a harmless Streamlit notice that appears when it runs outside a browser
    # (set after importing Streamlit, which configures its own loggers)
    logging.getLogger("streamlit.runtime.scriptrunner_utils.script_run_context").setLevel(logging.ERROR)
    print(f"streamlit {streamlit.__version__}, plotly {plotly.__version__}")

    app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    app.run()
    if app.exception:
        print(f"FAILED: the dashboard raised an error on startup:\n{app.exception}")
        return 1

    metrics = {metric.label: metric.value for metric in app.metric}
    print("\nStudy overview metrics:")
    for label, value in metrics.items():
        print(f"  {label}: {value}")

    for site_id in SITES_TO_CHECK:
        app.sidebar.selectbox[0].select(site_id).run()
        if app.exception:
            print(f"FAILED: selecting {site_id} raised an error:\n{app.exception}")
            return 1
        site_metrics = {metric.label: metric.value for metric in app.metric}
        warnings = [w.value for w in app.warning if not str(w.value).startswith("Demo only")]
        print(f"\n{app.header[0].value}")
        print(f"  Risk score: {site_metrics['Risk Score']}, deviations: {site_metrics['Total Deviations']}")
        if warnings:
            for warning in warnings:
                print(f"  Warning: {warning}")
        else:
            print("  " + "; ".join(str(s.value) for s in app.success))

    print("\nDashboard check finished OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
