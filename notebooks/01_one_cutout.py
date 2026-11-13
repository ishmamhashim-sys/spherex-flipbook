"""
Step 3 — One real IRSA SPHEREx cutout of WISE 0855.
Run: python notebooks/01_one_cutout.py
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
    print(f"Finding epochs at RA={ra} Dec={dec} FOV={fov}…")
    epochs = irsa.find_epochs(ra, dec, fov)
    print(f"Found {len(epochs)} epochs")
    if not epochs:
        print("FAIL: no epochs. Check IRSA / release.")
        sys.exit(1)

    ep = epochs[0]
    url = irsa.cutout_url(ep, ra, dec, fov)
    print("Downloading:", url[:160])
    fits_bytes = irsa.download_fits(url)
    data, header, flags = proc.load_image_hdu(fits_bytes)
    print("shape:", data.shape, "flags:", flags is not None)

    if data.ndim == 3:
        # mid-band slice + broadband
        mid = data[data.shape[0] // 2]
        broadband = proc.collapse_cube(data)
    else:
        mid = data
        broadband = data

    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].imshow(proc.asinh_stretch(mid), origin="lower", cmap="gray")
    ax[0].set_title("mid-band slice")
    ax[1].imshow(proc.asinh_stretch(broadband), origin="lower", cmap="gray")
    ax[1].set_title("broadband nansum")
    fig.suptitle(f"WISE 0855 cutout · {ep['id']} · MJD {ep['mjd']:.3f}")
    path = OUT / "01_one_cutout.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    print("Saved", path)
    print("GATE: open the PNG — star should be visible near center.")


if __name__ == "__main__":
    main()
