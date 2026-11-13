"""SPHEREx Flipbook API — FastAPI entrypoint."""
from __future__ import annotations

import io
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import (
    CACHE_DIR,
    DEFAULT_DEC,
    DEFAULT_FOV,
    DEFAULT_RA,
    RELEASE,
    ROOT,
    USE_ASYNC_JOBS,
)
from app import fake as fake_mod
from app import irsa
from app import jobs as jobmod
from app import process as proc

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("spherex_flipbook")

app = FastAPI(title="SPHEREx Flipbook API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory epoch list cache (coords → epochs)
_EPOCH_CACHE: dict[str, list[dict[str, Any]]] = {}
_REF_HEADER: dict[str, Any] = {}
_FITS_CACHE: dict[str, bytes] = {}
_META_CACHE: dict[str, dict[str, Any]] = {}


def _epoch_key(ra: float, dec: float, fov: float, release: str, band: str) -> str:
    return f"{ra:.5f}:{dec:.5f}:{fov:.4f}:{release}:{band}"


@app.get("/health")
def health():
    return {
        "ok": True,
        "release": RELEASE,
        "use_async_jobs": USE_ASYNC_JOBS,
        "cache_dir": str(CACHE_DIR),
    }


@app.get("/api/resolve")
def resolve(name: str = Query(..., min_length=1)):
    """Resolve object name → RA/Dec via Sesame / SkyCoord.from_name."""
    try:
        from astropy.coordinates import SkyCoord

        c = SkyCoord.from_name(name)
        return {"name": name, "ra": float(c.ra.degree), "dec": float(c.dec.degree)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, f"Could not resolve '{name}': {exc}") from exc


def _list_frames_payload(
    ra: float,
    dec: float,
    fov: float,
    release: str | None,
    band: str,
    source: str,
) -> dict[str, Any]:
    """List epochs covering the sky patch. Images are NOT included."""
    rel = release or RELEASE
    key = _epoch_key(ra, dec, fov, rel, band)

    if source == "fake":
        flist = fake_mod.fake_frame_list(ra, dec, fov)
        return {
            "ra": ra,
            "dec": dec,
            "fov": fov,
            "release": rel,
            "source": "fake",
            "n_frames": len(flist),
            "frames": flist,
            "warning": "Placeholder frames — not real SPHEREx data.",
        }

    if key in _EPOCH_CACHE and source != "real":
        flist = _EPOCH_CACHE[key]
        return {
            "ra": ra,
            "dec": dec,
            "fov": fov,
            "release": rel,
            "source": "real",
            "n_frames": len(flist),
            "frames": [
                {"id": e["id"], "mjd": e["mjd"], "band": e["band"], "status": e["status"]}
                for e in flist
            ],
        }

    try:
        t0 = time.time()
        flist = irsa.find_epochs(ra, dec, fov, bandpass=band if band != "all" else None, release=rel)
        log.info("find_epochs returned %d in %.2fs", len(flist), time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        log.exception("IRSA discovery failed")
        if source == "real":
            raise HTTPException(502, f"IRSA discovery failed: {exc}") from exc
        flist = []

    if not flist:
        flist = fake_mod.fake_frame_list(ra, dec, fov)
        return {
            "ra": ra,
            "dec": dec,
            "fov": fov,
            "release": rel,
            "source": "fake",
            "n_frames": len(flist),
            "frames": flist,
            "warning": "No IRSA epochs found — showing FAKE placeholders.",
        }

    seen: set[str] = set()
    uniq = []
    for e in flist:
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        uniq.append(e)
    uniq.sort(key=lambda e: e["mjd"])

    # When band=all, keep one detector per time bucket so the blink is temporal
    if band in ("all", "broadband") and len(uniq) > 12:
        by_time: dict[int, dict[str, Any]] = {}
        prefer = ("SPHEREx-D3", "SPHEREx-D2", "SPHEREx-D1", "SPHEREx-D4", "SPHEREx-D5", "SPHEREx-D6")
        for e in uniq:
            bucket = int(round(float(e["mjd"]) * 10))  # 0.1 day bins
            cur = by_time.get(bucket)
            if cur is None:
                by_time[bucket] = e
            else:
                try:
                    if prefer.index(e["band"]) < prefer.index(cur["band"]):
                        by_time[bucket] = e
                except ValueError:
                    pass
        uniq = sorted(by_time.values(), key=lambda e: e["mjd"])

    _EPOCH_CACHE[key] = uniq

    return {
        "ra": ra,
        "dec": dec,
        "fov": fov,
        "release": rel,
        "source": "real",
        "n_frames": len(uniq),
        "frames": [
            {"id": e["id"], "mjd": e["mjd"], "band": e["band"], "status": e["status"]}
            for e in uniq
        ],
    }


@app.get("/api/frames")
def frames(
    ra: float = Query(DEFAULT_RA, ge=0, lt=360),
    dec: float = Query(DEFAULT_DEC, ge=-90, le=90),
    fov: float = Query(DEFAULT_FOV, gt=0, le=2.0),
    release: str = Query(None),
    band: str = Query("all"),
    source: str = Query("auto"),  # auto | real | fake
):
    return JSONResponse(_list_frames_payload(ra, dec, fov, release, band, source))


def _get_epoch(ra, dec, fov, release, band, obs_id) -> dict[str, Any]:
    key = _epoch_key(ra, dec, fov, release or RELEASE, band)
    flist = _EPOCH_CACHE.get(key)
    if not flist:
        _list_frames_payload(ra, dec, fov, release, band, "auto")
        flist = _EPOCH_CACHE.get(key) or []
    for e in flist:
        if str(e["id"]) == str(obs_id):
            return e
    # fake numeric ids
    if str(obs_id).isdigit():
        return {"id": str(obs_id), "mjd": 0, "band": "fake", "status": "placeholder", "fake": True}
    raise HTTPException(404, f"Unknown obs_id {obs_id}")


@app.get("/api/frame/{obs_id}")
def frame(
    obs_id: str,
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
    fov: float = Query(DEFAULT_FOV, gt=0, le=2.0),
    release: str = Query(None),
    band: str = Query("all"),
    mode: str = Query("sum"),
    a: float = Query(0.1, gt=0, le=10),
    invert: int = Query(1),
    align: int = Query(1),
    source: str = Query("auto"),
):
    """Return a single PNG for one epoch (cached on disk)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rel = release or RELEASE
    key = proc.cache_key(ra, dec, fov, obs_id, rel, mode=f"{mode}_a{a}_i{invert}_al{align}")
    path = proc.cache_path(key)
    if path.exists():
        return Response(path.read_bytes(), media_type="image/png")

    def _save(png: bytes) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png)
        except OSError as exc:
            log.warning("cache write failed (%s); serving in-memory only", exc)

    if source == "fake":
        png = fake_mod.render_fake_png(int(obs_id) if str(obs_id).isdigit() else 0, ra, dec, fov)
        _save(png)
        return Response(png, media_type="image/png")

    try:
        epoch = _get_epoch(ra, dec, fov, rel, band, obs_id)
    except HTTPException:
        if str(obs_id).isdigit():
            epoch = {"id": str(obs_id), "band": "fake", "status": "placeholder", "fake": True}
        else:
            raise

    if epoch.get("fake") or epoch.get("band") == "fake" or epoch.get("status") == "placeholder":
        png = fake_mod.render_fake_png(int(obs_id) if str(obs_id).isdigit() else 0, ra, dec, fov)
        _save(png)
        return Response(png, media_type="image/png")

    try:
        url = irsa.cutout_url(epoch, ra, dec, fov)
        fits_key = f"{obs_id}:{ra:.5f}:{dec:.5f}:{fov:.4f}"
        if fits_key not in _FITS_CACHE:
            log.info("Downloading cutout %s", url[:120])
            _FITS_CACHE[fits_key] = irsa.download_fits(url)
        fits_bytes = _FITS_CACHE[fits_key]

        ref_header = None
        if align:
            ref_header = _REF_HEADER.get(f"{ra:.5f}:{dec:.5f}:{fov:.4f}")
            if ref_header is None:
                # establish reference from this first successful frame
                _, hdr, _ = proc.load_image_hdu(fits_bytes)
                _REF_HEADER[f"{ra:.5f}:{dec:.5f}:{fov:.4f}"] = hdr
                ref_header = None  # first frame is reference; no reproject needed

        png, meta = proc.process_fits_to_png(
            fits_bytes,
            mode=mode,
            a=a,
            invert=bool(invert),
            ref_header=ref_header,
        )
        _META_CACHE[key] = meta
        _save(png)
        return Response(png, media_type="image/png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("frame processing failed for %s", obs_id)
        png = fake_mod.render_fake_png(hash(obs_id) % 8, ra, dec, fov)
        return Response(
            png,
            media_type="image/png",
            headers={"X-Fallback": "fake", "X-Error": str(exc)[:200]},
        )


@app.get("/api/meta/{obs_id}")
def meta(
    obs_id: str,
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
    fov: float = Query(DEFAULT_FOV),
    release: str = Query(None),
    band: str = Query("all"),
    mode: str = Query("sum"),
):
    """Return processing metadata including FLAGS summary and spectrum if available."""
    rel = release or RELEASE
    key = proc.cache_key(ra, dec, fov, obs_id, rel, mode=mode)
    if key in _META_CACHE:
        return _META_CACHE[key]
    # Trigger frame build
    frame(obs_id=obs_id, ra=ra, dec=dec, fov=fov, release=rel, band=band, mode=mode)
    return _META_CACHE.get(key, {})


@app.get("/api/diff")
def diff(
    id_a: str = Query(...),
    id_b: str = Query(...),
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
    fov: float = Query(DEFAULT_FOV),
    release: str = Query(None),
    band: str = Query("all"),
    a: float = Query(0.1),
):
    """Difference imaging: epoch A minus epoch B."""
    rel = release or RELEASE
    ea = _get_epoch(ra, dec, fov, rel, band, id_a)
    eb = _get_epoch(ra, dec, fov, rel, band, id_b)
    if ea.get("band") == "fake" or eb.get("band") == "fake":
        raise HTTPException(400, "Difference needs real frames")
    try:
        ba = irsa.download_fits(irsa.cutout_url(ea, ra, dec, fov))
        bb = irsa.download_fits(irsa.cutout_url(eb, ra, dec, fov))
        png = proc.difference_png(ba, bb, a=a)
        return Response(png, media_type="image/png")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"diff failed: {exc}") from exc


@app.get("/api/gif")
def gif(
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
    fov: float = Query(DEFAULT_FOV),
    release: str = Query(None),
    band: str = Query("all"),
    speed: int = Query(400, ge=50, le=3000),
    max_frames: int = Query(12, ge=2, le=40),
):
    """Export a GIF of the blink sequence."""
    from PIL import Image

    rel = release or RELEASE
    data = _list_frames_payload(ra, dec, fov, rel, band, "auto")
    flist = data.get("frames", [])[:max_frames]
    imgs = []
    for fr in flist:
        resp = frame(obs_id=str(fr["id"]), ra=ra, dec=dec, fov=fov, release=rel, band=band)
        im = Image.open(io.BytesIO(resp.body)).convert("P")
        imgs.append(im)
    if not imgs:
        raise HTTPException(404, "No frames to export")
    buf = io.BytesIO()
    imgs[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=imgs[1:],
        duration=speed,
        loop=0,
    )
    return Response(buf.getvalue(), media_type="image/gif")


@app.get("/api/targets")
def targets():
    return {
        "targets": [
            {"name": "WISE 0855", "ra": 133.795, "dec": -7.245},
            {"name": "Barnard's Star", "ra": 269.452076, "dec": 4.693351},
            {"name": "Epsilon Indi", "ra": 330.840334, "dec": -56.785978},
            {"name": "RW Aurigae", "ra": 76.469136, "dec": 30.401234},
            {"name": "R Draconis", "ra": 246.52525, "dec": 66.67336},
        ]
    }


@app.post("/api/prepare")
@app.get("/api/prepare")
def prepare(
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
    fov: float = Query(DEFAULT_FOV),
    release: str = Query(None),
    band: str = Query("all"),
    mode: str = Query("sum"),
    a: float = Query(0.1),
    max_frames: int = Query(10, ge=1, le=24),
):
    """Enqueue background cutout processing; poll /api/job/{id} until ready."""
    rel = release or RELEASE
    payload = _list_frames_payload(ra, dec, fov, rel, band, "auto")
    flist = payload.get("frames", [])[:max_frames]
    job_id = jobmod.create_job(
        "prepare_frames",
        meta={"ra": ra, "dec": dec, "fov": fov, "n": len(flist), "source": payload.get("source")},
    )
    jobmod.update_job(job_id, total=len(flist), progress=0)

    def _work() -> None:
        for i, fr in enumerate(flist):
            try:
                frame(
                    obs_id=str(fr["id"]),
                    ra=ra,
                    dec=dec,
                    fov=fov,
                    release=rel,
                    band=band,
                    mode=mode,
                    a=a,
                    invert=1,
                    align=1,
                    source="auto" if payload.get("source") == "real" else "fake",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("prepare frame %s failed: %s", fr.get("id"), exc)
            jobmod.update_job(job_id, progress=i + 1)
        jobmod.update_job(
            job_id,
            result={
                "frames": flist,
                "source": payload.get("source"),
                "warning": payload.get("warning"),
            },
        )

    if payload.get("source") == "fake" or not USE_ASYNC_JOBS:
        _work()
        jobmod.update_job(job_id, status="ready")
    else:
        jobmod.run_in_background(job_id, _work)

    return {
        "job_id": job_id,
        "status": jobmod.get_job(job_id)["status"],
        "n_frames": len(flist),
        "frames": flist,
        "source": payload.get("source"),
        "warning": payload.get("warning"),
        "async": USE_ASYNC_JOBS and payload.get("source") == "real",
    }


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    job = jobmod.get_job(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return job


@app.get("/api/most")
def most_link(
    ra: float = Query(DEFAULT_RA),
    dec: float = Query(DEFAULT_DEC),
):
    """Helper link into IRSA MOST (Moving Object Search Tool) — do not reimplement orbits."""
    return {
        "tool": "IRSA MOST",
        "docs": "https://irsa.ipac.caltech.edu/applications/MOST/",
        "hint": "Use MOST for predicted solar-system positions at SPHEREx epochs.",
        "sky_position": {"ra": ra, "dec": dec},
    }


# Static frontend last
static_dir = ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
