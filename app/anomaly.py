"""SNR dipole / anomaly detection on SPHEREx epoch differences (Faiyaz port)."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import numpy as np

from app import process as proc

log = logging.getLogger(__name__)


def detect_anomalies(
    difference: np.ndarray,
    header,
    *,
    sigma_thresh: float = 3.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Detect high-SNR positive/negative peaks (dipoles) in A−B difference.

    Ported from faiyazkon/spherex_challenge pipeline.detect_anomalies.
    """
    from astropy.stats import sigma_clipped_stats
    from astropy.wcs import WCS
    from scipy.ndimage import maximum_filter, minimum_filter

    diff = np.asarray(difference, dtype=np.float64)
    valid = np.isfinite(diff)
    if not np.any(valid):
        return [], {"mean": 0.0, "median": 0.0, "std": 1.0, "sigma_threshold": float(sigma_thresh)}

    mean, median, std = sigma_clipped_stats(diff, sigma=3.0, maxiters=5)
    if std == 0 or not np.isfinite(std):
        std = float(np.nanstd(diff) or 1.0)

    snr_array = (diff - median) / std
    filled_pos = np.where(valid, diff, -np.inf)
    filled_neg = np.where(valid, diff, np.inf)
    is_local_max = filled_pos == maximum_filter(
        filled_pos, size=3, mode="constant", cval=-np.inf
    )
    is_local_min = filled_neg == minimum_filter(
        filled_neg, size=3, mode="constant", cval=np.inf
    )

    pos_mask = valid & (snr_array >= sigma_thresh) & is_local_max
    neg_mask = valid & (snr_array <= -sigma_thresh) & is_local_min

    try:
        wcs = WCS(header, naxis=2)
    except Exception:  # noqa: BLE001
        wcs = WCS(header).celestial

    anomalies: list[dict[str, Any]] = []
    for y, x in zip(*np.where(pos_mask)):
        try:
            coord = wcs.pixel_to_world(float(x), float(y))
            ra = round(float(coord.ra.deg), 6)
            dec = round(float(coord.dec.deg), 6)
        except Exception:  # noqa: BLE001
            ra, dec = float("nan"), float("nan")
        anomalies.append(
            {
                "pixel_x": int(x),
                "pixel_y": int(y),
                "ra": ra,
                "dec": dec,
                "snr": round(float(snr_array[y, x]), 2),
                "flux_diff": round(float(diff[y, x]), 5),
                "type": "Positive Dipole (New / Brightened)",
            }
        )

    for y, x in zip(*np.where(neg_mask)):
        try:
            coord = wcs.pixel_to_world(float(x), float(y))
            ra = round(float(coord.ra.deg), 6)
            dec = round(float(coord.dec.deg), 6)
        except Exception:  # noqa: BLE001
            ra, dec = float("nan"), float("nan")
        anomalies.append(
            {
                "pixel_x": int(x),
                "pixel_y": int(y),
                "ra": ra,
                "dec": dec,
                "snr": round(float(snr_array[y, x]), 2),
                "flux_diff": round(float(diff[y, x]), 5),
                "type": "Negative Dipole (Faded / Moved Away)",
            }
        )

    anomalies.sort(key=lambda a: abs(a["snr"]), reverse=True)
    stats = {
        "mean": round(float(mean), 6),
        "median": round(float(median), 6),
        "std": round(float(std), 6),
        "sigma_threshold": float(sigma_thresh),
    }
    return anomalies, stats


def subtract_fits_bytes(
    a_bytes: bytes,
    b_bytes: bytes,
    *,
    mode: str = "sum",
    sigma_thresh: float = 3.0,
    stretch_a: float = 0.1,
) -> dict[str, Any]:
    """Full A−B pipeline: clean, align, detect, render PNG bytes."""
    aa, ha, meta_a = proc.prepare_epoch_arrays(a_bytes, mode=mode)
    bb, hb, meta_b = proc.prepare_epoch_arrays(b_bytes, mode=mode)
    aligned_b, diff = proc.difference_arrays(aa, ha, bb, hb)
    anomalies, stats = detect_anomalies(diff, ha, sigma_thresh=sigma_thresh)
    png = proc.array_to_png_bytes(
        proc.asinh_stretch(diff, a=stretch_a, invert=False, p_low=5, p_high=95)
    )
    return {
        "png": png,
        "anomalies": anomalies,
        "stats": stats,
        "grid_shape": [int(s) for s in diff.shape],
        "meta_a": meta_a,
        "meta_b": meta_b,
        "aligned_shape": [int(s) for s in aligned_b.shape],
    }


def diff_png_url(
    *,
    id_a: str,
    id_b: str,
    ra: float,
    dec: float,
    fov: float,
    band: str = "all",
    mode: str = "sum",
    a: float = 0.1,
) -> str:
    q = urlencode(
        {
            "id_a": id_a,
            "id_b": id_b,
            "ra": ra,
            "dec": dec,
            "fov": fov,
            "band": band,
            "mode": mode,
            "a": a,
        }
    )
    return f"/api/diff?{q}"
