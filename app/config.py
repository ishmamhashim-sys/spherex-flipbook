"""Single place for release and path settings."""
from __future__ import annotations

import os
from pathlib import Path

# Prefer DR1; switch to "qr3" if DR1 TAP collections are unavailable.
RELEASE = os.environ.get("SPHEREX_RELEASE", "dr1")

# IRSA TAP collections to try, in order (first that returns rows wins for discovery).
RELEASE_COLLECTIONS = {
    "dr1": ("spherex_dr1", "spherex_dr1_deep", "spherex"),
    "qr3": ("spherex_qr3", "spherex_qr3_deep", "spherex"),
}

ROOT = Path(__file__).resolve().parent.parent

def _default_cache_dir() -> Path:
    env = os.environ.get("CACHE_DIR")
    if env:
        p = Path(env)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass
    for candidate in (ROOT / "cache", Path(os.environ.get("TEMP", "/tmp")) / "spherex_flipbook_cache"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # probe write
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return Path(os.environ.get("TEMP", ".")) / "spherex_flipbook_cache"

CACHE_DIR = _default_cache_dir()

IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP"
IRSA_BASE = "https://irsa.ipac.caltech.edu"

# Default demo target: WISE 0855
DEFAULT_RA = 133.795
DEFAULT_DEC = -7.245
DEFAULT_FOV = 0.1

# Sync vs async: Step 5 measured median ~18s → default async prep jobs on.
USE_ASYNC_JOBS = os.environ.get("USE_ASYNC_JOBS", "1") == "1"
