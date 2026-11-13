"""
Step 4 — Collapse two epochs, align, difference sanity check.
Run: python notebooks/02_collapse_align.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app import irsa
from app import process as proc
from app.config import DEFAULT_DEC, DEFAULT_FOV, DEFAULT_RA, ROOT as PROJECT_ROOT

import tempfile
OUT = Path(tempfile.gettempdir()) / "spherex_nb_out"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    ra, dec, fov = DEFAULT_RA, DEFAULT_DEC, DEFAULT_FOV
    epochs = irsa.find_epochs(ra, dec, fov)
    if len(epochs) < 2:
        print(f"Need >=2 epochs, got {len(epochs)}")
        sys.exit(1)

    # Pick two well-separated in time if possible
    e0, e1 = epochs[0], epochs[-1]
    print("Epoch A", e0["id"], e0["mjd"])
    print("Epoch B", e1["id"], e1["mjd"])

    b0 = irsa.download_fits(irsa.cutout_url(e0, ra, dec, fov))
    b1 = irsa.download_fits(irsa.cutout_url(e1, ra, dec, fov))
    d0, h0, _ = proc.load_image_hdu(b0)
    d1, h1, _ = proc.load_image_hdu(b1)
    a0 = proc.collapse_cube(d0)
    a1 = proc.collapse_cube(d1)

    aligned = False
    try:
        a1r = proc.reproject_to_reference(a1, h1, h0)
        aligned = True
    except Exception as exc:  # noqa: BLE001
        print("reproject failed, cutout-centering fallback:", exc)
        ny = min(a0.shape[0], a1.shape[0])
        nx = min(a0.shape[1], a1.shape[1])
        a1r = a1[:ny, :nx]
        a0 = a0[:ny, :nx]

    diff = a0 - a1r
    fig, ax = plt.subplots(1, 3, figsize=(12, 4))
    ax[0].imshow(proc.asinh_stretch(a0), origin="lower", cmap="gray")
    ax[0].set_title(f"A MJD {e0['mjd']:.1f}")
    ax[1].imshow(proc.asinh_stretch(a1r), origin="lower", cmap="gray")
    ax[1].set_title(f"B aligned={aligned}")
    ax[2].imshow(proc.asinh_stretch(diff, invert=False, p_low=5, p_high=95), origin="lower", cmap="gray")
    ax[2].set_title("A − B")
    path = OUT / "02_align_diff.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    print("Saved", path)
    print("GATE: random noise in diff => alignment OK; strong dipole => WCS issue.")


if __name__ == "__main__":
    main()
