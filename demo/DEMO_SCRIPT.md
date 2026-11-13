# 60-second demo script

1. Start server: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. Open http://127.0.0.1:8000/?ra=133.795&dec=-7.245&fov=0.1
3. Confirm badge says REAL IRSA (or honestly note FAKE fallback).
4. Let blink run one loop; call out loop-flash border.
5. Point at WISE 0855 motion.
6. FOV → 0.5 → Load.
7. Toggle Gaia DR3.
8. Optional: Diff A−B, Export GIF, preset another target.
