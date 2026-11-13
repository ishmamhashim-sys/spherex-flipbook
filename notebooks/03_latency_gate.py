"""
Step 5 — Latency gate: fetch → collapse → reproject → stretch ×3, median.
Run: python notebooks/03_latency_gate.py
Writes notebooks/out/latency.json and sets recommendation.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import irsa
from app import process as proc
from app.config import DEFAULT_DEC, DEFAULT_FOV, DEFAULT_RA, ROOT as PROJECT_ROOT

import tempfile
OUT = Path(tempfile.gettempdir()) / "spherex_nb_out"
OUT.mkdir(parents=True, exist_ok=True)


def one_cycle(epoch, ra, dec, fov, ref_header=None):
    t0 = time.time()
    fits_bytes = irsa.download_fits(irsa.cutout_url(epoch, ra, dec, fov))
    t_fetch = time.time() - t0
    t1 = time.time()
    data, header, _ = proc.load_image_hdu(fits_bytes)
    img = proc.collapse_cube(data)
    t_collapse = time.time() - t1
    t2 = time.time()
    if ref_header is not None:
        try:
            img = proc.reproject_to_reference(img, header, ref_header)
            aligned = True
        except Exception:
            aligned = False
    else:
        aligned = False
        ref_header = header
    t_reproject = time.time() - t2
    t3 = time.time()
    _ = proc.array_to_png_bytes(proc.asinh_stretch(img))
    t_stretch = time.time() - t3
    total = time.time() - t0
    return {
        "total": total,
        "fetch": t_fetch,
        "collapse": t_collapse,
        "reproject": t_reproject,
        "stretch": t_stretch,
        "aligned": aligned,
        "header": header,
    }


def main():
    ra, dec, fov = DEFAULT_RA, DEFAULT_DEC, DEFAULT_FOV
    epochs = irsa.find_epochs(ra, dec, fov)
    if not epochs:
        print("No epochs")
        sys.exit(1)
    ep = epochs[0]
    times = []
    ref = None
    details = []
    for i in range(3):
        print(f"Run {i+1}/3…")
        r = one_cycle(ep, ra, dec, fov, ref_header=ref)
        if ref is None:
            ref = r.pop("header", None)
        else:
            r.pop("header", None)
        details.append(r)
        times.append(r["total"])
        print(f"  total={r['total']:.2f}s fetch={r['fetch']:.2f}s")

    med = statistics.median(times)
    if med < 5:
        decision = "sync"
        note = "Median < 5s → synchronous FastAPI endpoints are fine."
    elif med > 10:
        decision = "async"
        note = "Median > 10s → use job queue + poll."
    else:
        decision = "sync_preferred"
        note = "5–10s grey zone → prefer sync with aggressive caching for demo."

    result = {
        "median_seconds": med,
        "runs": times,
        "details": details,
        "decision": decision,
        "note": note,
        "obs_id": ep["id"],
    }
    path = OUT / "latency.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print("Wrote", path)


if __name__ == "__main__":
    main()
