"""Step 11 — Probe all five challenge targets via the API helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import _list_frames_payload

TARGETS = [
    {"name": "WISE 0855", "ra": 133.795, "dec": -7.245},
    {"name": "Barnard's Star", "ra": 269.452076, "dec": 4.693351},
    {"name": "Epsilon Indi", "ra": 330.840334, "dec": -56.785978},
    {"name": "RW Aurigae", "ra": 76.469136, "dec": 30.401234},
    {"name": "R Draconis", "ra": 246.52525, "dec": 66.67336},
]


def main():
    results = []
    for t in TARGETS:
        print("===", t["name"], "===")
        try:
            payload = _list_frames_payload(t["ra"], t["dec"], 0.1, None, "all", "auto")
            results.append(
                {
                    "name": t["name"],
                    "ok": True,
                    "source": payload.get("source"),
                    "n_frames": payload.get("n_frames"),
                    "warning": payload.get("warning"),
                }
            )
            print(" ", payload.get("source"), "n=", payload.get("n_frames"))
        except Exception as exc:  # noqa: BLE001
            results.append({"name": t["name"], "ok": False, "error": str(exc)})
            print("  FAIL", exc)
    import tempfile
    out = Path(tempfile.gettempdir()) / "spherex_target_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print("Wrote", out)


if __name__ == "__main__":
    main()
