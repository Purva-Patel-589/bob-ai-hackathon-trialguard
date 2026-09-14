"""
pytest setup: make the src/ folder importable from the tests, so tests can
write `import config` and `from utils.data_loader import ...` exactly like
the app does.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
