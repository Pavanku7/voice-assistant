"""
Meryna — web entry point.

Thin wrapper so ``streamlit run app.py`` continues to work after the platform
restructure.  The real interface lives in ``interfaces/web/app.py``; we execute
it fresh on every Streamlit rerun (a plain ``import`` would be cached and only
run once).

Requirements addressed: 9.1
"""

import runpy
from pathlib import Path

_WEB_APP = Path(__file__).resolve().parent / "interfaces" / "web" / "app.py"

runpy.run_path(str(_WEB_APP), run_name="__main__")
