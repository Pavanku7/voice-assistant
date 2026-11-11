# Meryna Platform Core Package
#
# This package is deliberately named ``platform`` to match the layered design
# of the Meryna Voice Platform.  Unfortunately that shadows Python's standard
# library ``platform`` module, which several third-party dependencies rely on
# (e.g. ``multidict`` → ``aiohttp`` → ``google-genai`` call
# ``platform.python_implementation()``).
#
# To keep both working, we load the genuine standard-library ``platform``
# module directly from its file location and merge its public attributes into
# this package's namespace.  Our own submodules (``core``, ``config``, etc.)
# are imported as normal subpackages and are unaffected.

import importlib.util as _ilu
import os as _os

# --- Re-export the real stdlib ``platform`` module's public attributes -------
try:
    _stdlib_platform_path = _os.path.join(
        _os.path.dirname(_os.__file__), "platform.py"
    )
    _spec = _ilu.spec_from_file_location("_stdlib_platform", _stdlib_platform_path)
    if _spec and _spec.loader:  # pragma: no branch
        _stdlib_platform = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_stdlib_platform)
        for _name in dir(_stdlib_platform):
            if not _name.startswith("_") and _name not in globals():
                globals()[_name] = getattr(_stdlib_platform, _name)
except Exception:  # noqa: BLE001 — never let this break package import
    pass

# --- Meryna platform exports -------------------------------------------------
from meryna_platform.logging import PlatformLogger  # noqa: E402,F401
