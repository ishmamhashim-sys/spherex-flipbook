# SPHEREx Flipbook — Submission notes

## One-liner
A public WiseView-style blink viewer for SPHEREx: enter RA/Dec, watch real IRSA cutouts flip through time, and spot movers by eye.

## Talking points
- We use IRSA’s Cutout Service rather than downloading full MEF files.
- We collapse 102 spectral bands with `np.nansum` (optional per-detector stack) for S/N.
- Release (`dr1` / `qr3`) is a single constant in `app/config.py`.
- URL parameters make every view shareable and embeddable.
- Viewer for human discovery, not an automated detector.
- Gaia DR3 overlay via Aladin Lite as an “answer key.”
- Difference imaging (+/− legend), FLAGS-aware masking, on-the-fly spectrum metadata, GIF export.

## Demo script (~60s)
1. Open `/?ra=133.795&dec=-7.245&fov=0.1` (WISE 0855).
2. Press play; let one full loop run; point out the dashed border flash on reset.
3. Note the moving source against fixed stars.
4. Change FOV to `0.5` and reload.
5. Toggle Gaia DR3 on the Aladin panel.
6. Optionally toggle Diff A−B and Export GIF.
7. If a target falls back to FAKE frames, say so honestly.

## Test targets
See `/api/targets` and README table. Failures become known-issue notes, not blockers.

## References reused
- backyardworlds/wiseview (UX)
- Caltech-IPAC/irsa-tutorials (TAP/cutout)
- hbahk/spherex-retrieval / fkiwy/spexpi (patterns)
- cds-astro/aladin-lite (sky map + catalogs)
