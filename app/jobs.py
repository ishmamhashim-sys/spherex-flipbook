"""Simple in-memory async job queue for slow IRSA cutouts."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

log = logging.getLogger(__name__)

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def create_job(kind: str, meta: dict[str, Any] | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "pending",
            "created": time.time(),
            "updated": time.time(),
            "progress": 0,
            "total": 0,
            "error": None,
            "result": None,
            "meta": meta or {},
        }
    return job_id


def update_job(job_id: str, **kwargs: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(kwargs)
        job["updated"] = time.time()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def run_in_background(job_id: str, fn: Callable[[], None]) -> None:
    def _wrap() -> None:
        update_job(job_id, status="running")
        try:
            fn()
            cur = get_job(job_id)
            if cur and cur.get("status") != "error":
                update_job(job_id, status="ready", progress=cur.get("total") or 1)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            update_job(job_id, status="error", error=str(exc))

    threading.Thread(target=_wrap, daemon=True).start()
