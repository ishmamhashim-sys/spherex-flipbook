"""IRSA TAP discovery and cutout URL helpers for SPHEREx."""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any
import requests

from app.config import IRSA_TAP, RELEASE, RELEASE_COLLECTIONS

log = logging.getLogger(__name__)

# Whitelist only — never interpolate raw client bandpass into ADQL.
VALID_BANDPASSES = frozenset(
    {
        "SPHEREx-D1",
        "SPHEREx-D2",
        "SPHEREx-D3",
        "SPHEREx-D4",
        "SPHEREx-D5",
        "SPHEREx-D6",
    }
)


def _safe_bandpass(bandpass: str | None) -> str | None:
    """Return a whitelisted bandpass name, or None for no band filter."""
    if not bandpass or bandpass in ("all", "broadband"):
        return None
    if bandpass not in VALID_BANDPASSES:
        log.warning("ignoring invalid bandpass %r", bandpass)
        return None
    return bandpass


def _tap_sync(query: str, timeout: int = 180) -> str:
    r = requests.get(
        f"{IRSA_TAP}/sync",
        params={"QUERY": query, "FORMAT": "csv", "LANG": "ADQL"},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


def find_epochs(
    ra: float,
    dec: float,
    fov: float = 0.1,
    bandpass: str | None = None,
    release: str | None = None,
) -> list[dict[str, Any]]:
    """Return epoch metadata covering (ra, dec), sorted by MJD.

    Prefer spherex.artifact cutout URLs (direct FITS). ObsCore datalink
    URLs are a fallback only after resolution.
    """
    release = release or RELEASE
    epochs: list[dict[str, Any]] = []

    # Strategy 1: artifact + plane (official IRSA tutorials) — direct FITS cutouts
    try:
        epochs = _find_via_artifact(ra, dec, fov, bandpass)
        if epochs:
            log.info("artifact discovery: %d epochs", len(epochs))
            return _dedupe(epochs)
    except Exception as exc:  # noqa: BLE001
        log.warning("artifact query failed: %s", exc)

    # Strategy 2: spherex.obscore → resolve datalink to cutout if possible
    try:
        epochs = _find_via_obscore(ra, dec, fov, bandpass)
        if epochs:
            log.info("obscore discovery: %d epochs", len(epochs))
            return _dedupe(epochs)
    except Exception as exc:  # noqa: BLE001
        log.warning("obscore query failed: %s", exc)

    # Strategy 3: SIA2
    try:
        epochs = _find_via_sia2(ra, dec, fov, release, bandpass)
        if epochs:
            log.info("SIA2 discovery: %d epochs", len(epochs))
            return _dedupe(epochs)
    except Exception as exc:  # noqa: BLE001
        log.warning("SIA2 query failed: %s", exc)

    return epochs


def _dedupe(epochs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for e in epochs:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append(e)
    out.sort(key=lambda e: e["mjd"])
    return out


def _find_via_artifact(
    ra: float, dec: float, fov: float, bandpass: str | None
) -> list[dict[str, Any]]:
    safe = _safe_bandpass(bandpass)
    band_clause = f"AND p.energy_bandpassname = '{safe}'" if safe else ""
    # Note: IRSA tutorials use `{dec}d` unit suffix on Dec in the center param.
    query = f"""
SELECT TOP 60
  'https://irsa.ipac.caltech.edu/' || a.uri || '?center={ra},{dec}d&size={fov}' AS uri,
  p.time_bounds_lower AS t_min,
  p.energy_bandpassname AS band,
  a.uri AS path
FROM spherex.artifact a
JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', {ra}, {dec}), p.poly)
  {band_clause}
ORDER BY p.time_bounds_lower
"""
    text = _tap_sync(query)
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(reader):
        uri = (row.get("uri") or "").strip().strip('"')
        if not uri or "ibe/data" not in uri:
            continue
        mjd = float(row.get("t_min") or 0)
        band = (row.get("band") or "unknown").strip().strip('"')
        path = (row.get("path") or uri).strip().strip('"')
        obs_id = path.rstrip("/").split("/")[-1]
        for suf in (".fits.gz", ".fits"):
            if obs_id.endswith(suf):
                obs_id = obs_id[: -len(suf)]
                break
        if not obs_id:
            obs_id = f"artifact_{i}"
        out.append(
            {
                "id": obs_id,
                "mjd": mjd,
                "band": band,
                "status": "ok",
                "access_url": uri,
                "cutout_template": uri,
                "collection": "spherex.artifact",
            }
        )
    return out


def _find_via_obscore(
    ra: float, dec: float, fov: float, bandpass: str | None
) -> list[dict[str, Any]]:
    safe = _safe_bandpass(bandpass)
    band_clause = f"AND energy_bandpassname = '{safe}'" if safe else ""
    query = f"""
SELECT TOP 40 obs_id, obs_collection, t_min, access_url, energy_bandpassname
FROM spherex.obscore
WHERE CONTAINS(POINT('ICRS', {ra}, {dec}), s_region) = 1
  {band_clause}
ORDER BY t_min
"""
    text = _tap_sync(query)
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(reader):
        access = (row.get("access_url") or "").strip().strip('"')
        if not access:
            continue
        mjd = float(row.get("t_min") or 0)
        obs_id = (row.get("obs_id") or f"epoch_{i}").strip().strip('"')
        band = (row.get("energy_bandpassname") or "unknown").strip().strip('"')
        # Convert datalink / ivo ids into IBE cutout when possible
        cutout = _obscore_to_cutout(access, obs_id, ra, dec, fov)
        out.append(
            {
                "id": obs_id.replace("/", "_").replace("?", "_"),
                "mjd": mjd,
                "band": band,
                "status": "ok",
                "access_url": cutout,
                "cutout_template": cutout,
                "collection": (row.get("obs_collection") or "").strip().strip('"'),
            }
        )
    return out


def _obscore_to_cutout(access: str, obs_id: str, ra: float, dec: float, fov: float) -> str:
    """Best-effort: if access is already IBE FITS, append cutout; else keep access."""
    if "ibe/data" in access and access.endswith(".fits"):
        sep = "&" if "?" in access else "?"
        return f"{access}{sep}center={ra},{dec}d&size={fov}"
    if "ibe/data" in access and ".fits?" in access:
        return access
    # Leave datalink as-is; download_fits will try to resolve VOTable
    if "center=" not in access:
        sep = "&" if "?" in access else "?"
        return f"{access}{sep}center={ra},{dec}&size={fov}"
    return access


def _find_via_sia2(
    ra: float,
    dec: float,
    fov: float,
    release: str,
    bandpass: str | None,
) -> list[dict[str, Any]]:
    from pyvo.dal import SIA2Service
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    collections = RELEASE_COLLECTIONS.get(release, ("spherex",))
    svc = SIA2Service("https://irsa.ipac.caltech.edu/SIA")
    coord = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
    out: list[dict[str, Any]] = []
    for coll in collections:
        try:
            results = svc.search((coord, fov * u.deg), collection=coll)
        except Exception as exc:  # noqa: BLE001
            log.warning("SIA2 collection %s failed: %s", coll, exc)
            continue
        table = results.to_table()
        for i, row in enumerate(table):
            access = str(row["access_url"]) if "access_url" in table.colnames else ""
            if not access:
                continue
            mjd = float(row["t_min"]) if "t_min" in table.colnames else float(i)
            obs_id = str(row["obs_id"]) if "obs_id" in table.colnames else f"{coll}_{i}"
            band = (
                str(row["energy_bandpassname"])
                if "energy_bandpassname" in table.colnames
                else "unknown"
            )
            safe = _safe_bandpass(bandpass)
            if safe and band != safe:
                continue
            if "ibe/data" in access and "center=" not in access:
                sep = "&" if "?" in access else "?"
                access = f"{access}{sep}center={ra},{dec}d&size={fov}"
            out.append(
                {
                    "id": obs_id.replace("/", "_"),
                    "mjd": mjd,
                    "band": band,
                    "status": "ok",
                    "access_url": access,
                    "cutout_template": access,
                    "collection": coll,
                }
            )
        if out:
            break
    out.sort(key=lambda e: e["mjd"])
    return out


def cutout_url(epoch: dict[str, Any], ra: float, dec: float, fov: float) -> str:
    tmpl = epoch.get("cutout_template") or epoch.get("access_url") or ""
    if "{fov}" in tmpl:
        return tmpl.format(fov=fov)
    if "center=" in tmpl and "size=" in tmpl:
        url = re.sub(r"size=[^&]+", f"size={fov}", tmpl)
        url = re.sub(r"center=[^&]+", f"center={ra},{dec}d", url)
        return url
    sep = "&" if "?" in tmpl else "?"
    return f"{tmpl}{sep}center={ra},{dec}d&size={fov}"


def download_fits(url: str, timeout: int = 180, retries: int = 4) -> bytes:
    import time

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} for {url[:80]}", response=r)
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            data = r.content
            if "votable" in ctype or data[:100].lstrip().startswith(b"<?xml"):
                fits_url = _parse_datalink_fits_url(data.decode("utf-8", errors="ignore"), url)
                if not fits_url:
                    raise RuntimeError(f"DataLink response had no FITS URL for {url[:120]}")
                r2 = requests.get(fits_url, timeout=timeout)
                r2.raise_for_status()
                return r2.content
            if not (data[:8] == b"SIMPLE  " or data[:6] == b"SIMPLE"):
                if b"NAXIS" not in data[:2880]:
                    raise RuntimeError(
                        f"Not a FITS payload ({ctype}, {len(data)} bytes) from {url[:120]}"
                    )
            return data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            sleep = 3 * (attempt + 1)
            log.warning("download attempt %d failed: %s; sleep %ds", attempt + 1, exc, sleep)
            time.sleep(sleep)
    raise RuntimeError(f"download_fits failed after {retries} tries: {last_err}")


def _parse_datalink_fits_url(xml_text: str, original: str) -> str | None:
    """Pull a plausible cutout/FITS access URL out of a DataLink VOTable."""
    # Prefer access_url TABLEDATA cells that look like FITS/IBE
    hrefs = re.findall(r"https://irsa\.ipac\.caltech\.edu/[^<\s\"']+", xml_text)
    for h in hrefs:
        h = h.rstrip(".,;")
        if "ibe/data" in h and ".fits" in h:
            return h
    for h in hrefs:
        if "cutout" in h.lower() or "ibe" in h:
            return h
    return None
