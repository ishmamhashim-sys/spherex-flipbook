# Known issues

- First-cutout latency median ≈ 18s (IRSA fetch dominated) → `/api/prepare` + job poll.
- Workspace `cache/` may be sandbox-blocked on some machines; runtime falls back to `%TEMP%\spherex_flipbook_cache`.
- Level-2 IBE cutouts for this release often arrive as 2D detector planes (not always a 102-plane cube in one file). Broadband sum still applies when cubes are 3D; otherwise the plane is shown as-is.
- Do not present FAKE placeholder frames as real SPHEREx data (UI badge warns).
