# SPHEREx Flipbook (Sky Blink)

NASA Space Apps Challenge 2026 — **Planet X and SPHEREx**.

Public web tool: enter sky coordinates → blink real SPHEREx cutouts over time to spot movers.

## Quick start

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# or: run.bat
```

Open: http://127.0.0.1:8000/?ra=133.795&dec=-7.245&fov=0.1

First load uses `/api/prepare` and may take ~15–20s per new frame (IRSA). Replays are cached.

## Test targets

| Target | RA (deg) | Dec (deg) |
|--------|----------|-----------|
| WISE 0855 | 133.795 | -7.245 |
| Barnard's Star | 269.452 | 4.693 |
| Epsilon Indi | 330.840 | -56.786 |
| RW Aurigae | 76.469 | 30.401 |
| R Draconis | 246.525 | 66.673 |

## Architecture

- `app/` — FastAPI backend (IRSA query, cutout, collapse, align, PNG cache)
- `static/` — Blink UI + Aladin Lite
- `notebooks/` — Data-path proofs (Steps 3–5)
- `refs/` — Cloned reference repos (study only)
- `cache/` — PNG thumbnails only (gitignored)
- `demo/` — Submission notes + demo script

Release is a single constant in `app/config.py` (`SPHEREX_RELEASE=dr1` or `qr3`).
