"""SPHEREx MEF → collapsed / aligned / stretched PNG."""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.config import CACHE_DIR, RELEASE

log = logging.getLogger(__name__)


def cache_key(
    ra: float,
    dec: float,
    fov: float,
    obs_id: str,
    release: str | None = None,
    mode: str = "sum",
) -> str:
    release = release or RELEASE
    s = f"{ra:.5f}_{dec:.5f}_{fov:.4f}_{obs_id}_{release}_{mode}"
    return hashlib.sha256(s.encode()).hexdigest()[:20]


def cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{key}.png"


def collapse_cube(cube: np.ndarray, mode: str = "sum") -> np.ndarray:
    """Collapse [wave, y, x] → 2D. Uses nansum so NaNs don't poison."""
    data = np.asarray(cube, dtype=np.float64)
    if data.ndim == 2:
        return data
    if data.ndim != 3:
        raise ValueError(f"Expected 2D or 3D cube, got shape {data.shape}")
    if mode == "median":
        return np.nanmedian(data, axis=0)
    if mode.startswith("detector"):
        # Per-detector stacks: sum wavelengths within each of 6 detector groups,
        # then equal-weight combine detectors (nanmean). That differs from a raw
        # broadband nansum, which lets detectors with more bands dominate.
        n = data.shape[0]
        groups = np.array_split(np.arange(n), 6)
        stacks = [np.nansum(data[g], axis=0) for g in groups if len(g)]
        if not stacks:
            return np.nansum(data, axis=0)
        return np.nanmean(np.stack(stacks, axis=0), axis=0)
    return np.nansum(data, axis=0)


# SPHEREx FLAGS bits to preserve (Faiyaz pipeline):
# bit 21 (2097152) = astronomical SOURCE; bit 1 (2) = benign calibration.
_FLAG_KEEP = 2097152 | 2  # 2097154


def _mid_slice(arr: np.ndarray) -> np.ndarray:
    """If spectral cube, take middle wavelength plane for 2-D ops."""
    data = np.asarray(arr)
    if data.ndim == 3:
        return data[data.shape[0] // 2]
    return data


def load_image_hdu(fits_bytes: bytes, *, subtract_zodi: bool = True):
    """Load IMAGE (+ optional ZODI/FLAGS). Returns (data, header, flags).

    When ZODI is present and subtract_zodi=True, returns IMAGE−ZODI.
    FLAGS are returned raw; smart masking is applied in process_fits_to_png /
    clean_spatial.
    """
    from astropy.io import fits

    with fits.open(io.BytesIO(fits_bytes)) as hdul:
        # Prefer EXTNAME IMAGE, else first extension with data, else HDU 1
        hdu = None
        for h in hdul:
            name = (h.name or "").upper()
            if name.startswith("IMAGE") and h.data is not None:
                hdu = h
                break
        if hdu is None:
            for h in hdul[1:]:
                if h.data is not None:
                    hdu = h
                    break
        if hdu is None:
            hdu = hdul[0]
        data = np.array(hdu.data, dtype=np.float64, copy=True)
        header = hdu.header.copy()

        if subtract_zodi and "ZODI" in hdul:
            try:
                zodi = np.array(hdul["ZODI"].data, dtype=np.float64, copy=True)
                if zodi.shape == data.shape:
                    data = data - zodi
                elif data.ndim == 3 and zodi.ndim == 2 and zodi.shape == data.shape[1:]:
                    data = data - zodi[np.newaxis, :, :]
                elif data.ndim == 2 and zodi.ndim == 3:
                    data = data - _mid_slice(zodi)
                else:
                    log.warning("ZODI shape %s != IMAGE shape %s; skip subtract", zodi.shape, data.shape)
            except Exception as exc:  # noqa: BLE001
                log.warning("ZODI subtract failed: %s", exc)

        flags = None
        if "FLAGS" in hdul:
            try:
                flags = np.array(hdul["FLAGS"].data, copy=True)
            except Exception:  # noqa: BLE001
                flags = None
        return data, header, flags


def smart_flag_mask(flags: np.ndarray | None) -> np.ndarray | None:
    """True where pixels are bad glitches (exclude SOURCE + benign bits)."""
    if flags is None:
        return None
    f2 = np.asarray(flags)
    if f2.ndim == 3:
        # Any wavelength plane with a true glitch bit → mask spatial pixel
        bad3 = (f2.astype(np.int64) & ~_FLAG_KEEP) != 0
        return np.any(bad3, axis=0)
    return (f2.astype(np.int64) & ~_FLAG_KEEP) != 0


def clean_spatial(
    data: np.ndarray,
    flags: np.ndarray | None,
    *,
    mode: str = "sum",
    mask_flags: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Collapse cube if needed and apply smart FLAGS mask. Returns 2-D + meta."""
    meta: dict[str, Any] = {
        "shape": list(np.asarray(data).shape),
        "has_flags": flags is not None,
        "zodi_path": True,
    }
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 3:
        meta["n_bands"] = int(arr.shape[0])
        meta["spectrum"] = extract_spectrum(arr)
        img2d = collapse_cube(arr, mode=mode)
    else:
        meta["n_bands"] = 1
        meta["spectrum"] = []
        img2d = arr

    if mask_flags and flags is not None:
        try:
            bad = smart_flag_mask(flags)
            if bad is not None and bad.shape == img2d.shape:
                img2d = img2d.copy()
                img2d[bad] = np.nan
                meta["flagged_pixels"] = int(np.sum(bad))
        except Exception as exc:  # noqa: BLE001
            log.warning("smart flag mask failed: %s", exc)
    return img2d, meta


def extract_spectrum(cube: np.ndarray, y: int | None = None, x: int | None = None) -> list[float]:
    """Mean spectrum at center pixel (or given y,x)."""
    data = np.asarray(cube, dtype=np.float64)
    if data.ndim != 3:
        return []
    _, ny, nx = data.shape
    yy = y if y is not None else ny // 2
    xx = x if x is not None else nx // 2
    yy = int(np.clip(yy, 0, ny - 1))
    xx = int(np.clip(xx, 0, nx - 1))
    spec = data[:, yy, xx]
    return [float(v) if np.isfinite(v) else float("nan") for v in spec]


def reproject_to_reference(
    data: np.ndarray,
    header,
    ref_header,
) -> np.ndarray:
    from astropy.wcs import WCS
    from reproject import reproject_interp

    # Spatial WCS only — drop spectral axes if present
    try:
        wcs_in = WCS(header, naxis=2)
        wcs_ref = WCS(ref_header, naxis=2)
    except Exception:  # noqa: BLE001
        wcs_in = WCS(header).celestial
        wcs_ref = WCS(ref_header).celestial

    shape = (int(ref_header.get("NAXIS2", data.shape[-2])), int(ref_header.get("NAXIS1", data.shape[-1])))
    if data.ndim == 3:
        data = collapse_cube(data)
    aligned, _ = reproject_interp((data, wcs_in), wcs_ref, shape_out=shape)
    return np.asarray(aligned, dtype=np.float64)


def asinh_stretch(
    data: np.ndarray,
    a: float = 0.1,
    p_low: float = 1.0,
    p_high: float = 99.5,
    invert: bool = True,
) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float64)
    finite = np.isfinite(arr)
    if not np.any(finite):
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = np.nanpercentile(arr[finite], [p_low, p_high])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(np.nanmin(arr[finite])), float(np.nanmax(arr[finite]))
        if hi <= lo:
            hi = lo + 1.0
    clipped = np.clip(arr, lo, hi)
    norm = (clipped - lo) / (hi - lo)
    # soft asinh stretch
    stretched = np.arcsinh(norm / max(a, 1e-6)) / np.arcsinh(1.0 / max(a, 1e-6))
    stretched = np.nan_to_num(stretched, nan=0.0, posinf=1.0, neginf=0.0)
    stretched = np.clip(stretched, 0, 1)
    if invert:
        stretched = 1.0 - stretched
    return (stretched * 255).astype(np.uint8)


def array_to_png_bytes(img8: np.ndarray) -> bytes:
    if img8.ndim == 2:
        im = Image.fromarray(img8, mode="L")
    else:
        im = Image.fromarray(img8)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def process_fits_to_png(
    fits_bytes: bytes,
    *,
    mode: str = "sum",
    a: float = 0.1,
    invert: bool = True,
    ref_header=None,
    mask_flags: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    data, header, flags = load_image_hdu(fits_bytes, subtract_zodi=True)
    img2d, meta = clean_spatial(data, flags, mode=mode, mask_flags=mask_flags)

    if ref_header is not None:
        try:
            img2d = reproject_to_reference(img2d, header, ref_header)
            meta["aligned"] = True
        except Exception as exc:  # noqa: BLE001
            log.warning("reproject failed, using cutout centering: %s", exc)
            meta["aligned"] = False
            meta["align_fallback"] = str(exc)
    else:
        meta["aligned"] = False

    png = array_to_png_bytes(asinh_stretch(img2d, a=a, invert=invert))
    meta["header_mjd"] = header.get("MJD-OBS") or header.get("MJD") or header.get("DATE-OBS")
    return png, meta


def prepare_epoch_arrays(
    fits_bytes: bytes,
    *,
    mode: str = "sum",
    mask_flags: bool = True,
) -> tuple[np.ndarray, Any, dict[str, Any]]:
    """Return cleaned 2-D image, FITS header, and meta for subtraction."""
    data, header, flags = load_image_hdu(fits_bytes, subtract_zodi=True)
    img2d, meta = clean_spatial(data, flags, mode=mode, mask_flags=mask_flags)
    return img2d, header, meta


def difference_arrays(
    img_a: np.ndarray,
    header_a,
    img_b: np.ndarray,
    header_b,
) -> tuple[np.ndarray, np.ndarray]:
    """Reproject B onto A's WCS; return (aligned_b, difference A−B)."""
    aa = np.asarray(img_a, dtype=np.float64)
    bb = np.asarray(img_b, dtype=np.float64)
    try:
        bb = reproject_to_reference(bb, header_b, header_a)
    except Exception as exc:  # noqa: BLE001
        log.warning("diff reproject failed, cropping: %s", exc)
        ny = min(aa.shape[0], bb.shape[0])
        nx = min(aa.shape[1], bb.shape[1])
        aa, bb = aa[:ny, :nx], bb[:ny, :nx]
    # Footprint holes from reproject are NaN; keep them
    diff = aa - bb
    return bb, diff


def difference_png(
    a_bytes: bytes,
    b_bytes: bytes,
    a: float = 0.1,
    *,
    mode: str = "sum",
) -> bytes:
    """Difference two FITS cutouts after ZODI clean, smart FLAGS, and WCS align."""
    aa, ha, _ = prepare_epoch_arrays(a_bytes, mode=mode)
    bb, hb, _ = prepare_epoch_arrays(b_bytes, mode=mode)
    _, diff = difference_arrays(aa, ha, bb, hb)
    return array_to_png_bytes(asinh_stretch(diff, a=a, invert=False, p_low=5, p_high=95))
