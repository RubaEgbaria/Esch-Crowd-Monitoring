"""Run storage: one folder per run, described by ``run.json``.

No database: ``data/runs/<run_id>/run.json`` is the source of truth and is
loaded into memory at startup. Processing results go to ``cache/<run_id>/``.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import stat
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AppError
from .jobs import Job
from .settings import Settings

log = logging.getLogger(__name__)

ROLES = ("lidar_zip", "camera_video", "lidar_screen")
REQUIRED_ROLES = ("lidar_zip", "camera_video")
ROLE_LABELS = {
    "lidar_zip": "LiDAR recording (.zip)",
    "camera_video": "Camera video",
    "lidar_screen": "Sensor UI recording",
}

# Statuses during which work is happening; after a backend restart such a run
# is marked "interrupted".
ACTIVE_STATUSES = {"uploading", "queued", "downloading", "validating", "processing"}

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (s or "run")[:max_len].strip("-") or "run"


def safe_filename(name: str) -> str:
    """Keep only the last path component, with filesystem-safe characters."""
    base = name.replace("\\", "/").split("/")[-1]
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "file"
    ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:10]
    return f"{stem[:100]}.{ext}" if ext else stem[:100]


def _rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files and retries (Windows)."""

    def on_error(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    for attempt in range(5):
        if not path.exists():
            return
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=on_error)
            else:
                shutil.rmtree(path, onerror=on_error)
        except OSError:
            pass
        if not path.exists():
            return
        time.sleep(0.2 * (attempt + 1))
    if path.exists():
        raise AppError(
            f"Could not delete {path.name}: a file is still in use. Close any program using it and try again.",
            code="delete_failed",
            status=409,
        )


class RunStore:
    """Thread-safe in-memory view of all runs, persisted to run.json files."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._jobs: dict[str, Job] = {}
        self._live_jobs: dict[str, Job] = {}     # Live view runs and exports
        self._last_save: dict[str, float] = {}
        self._load_all()

    # ------------------------------------------------------------- paths
    def run_dir(self, run_id: str) -> Path:
        return self.settings.runs_dir / run_id

    def cache_dir(self, run_id: str) -> Path:
        return self.settings.cache_dir / run_id

    def file_path(self, run_id: str, role: str) -> Path:
        run = self.get(run_id)
        f = run["files"].get(role)
        if not f:
            raise AppError(f"This run has no {ROLE_LABELS.get(role, role)}", code="no_file", status=404)
        return self.run_dir(run_id) / f["local_name"]

    # ------------------------------------------------------------- loading
    def _load_all(self) -> None:
        runs_dir = self.settings.runs_dir
        if not runs_dir.is_dir():
            return
        for d in sorted(runs_dir.iterdir()):
            f = d / "run.json"
            if not f.is_file():
                continue
            try:
                run = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning("Skipping unreadable %s: %s", f, e)
                continue
            if run.get("id") != d.name:
                log.warning("Skipping %s: id does not match its folder", f)
                continue
            if run.get("status") in ACTIVE_STATUSES:
                run["status"] = "interrupted"
                run["error"] = (
                    "The backend stopped while this run was in progress. "
                    "Use Rerun to continue."
                )
                self._interrupt(run.get("job"))
                self._write(run)
            if self._interrupt(run.get("live_job")):
                self._write(run)
            self._runs[run["id"]] = run

    @staticmethod
    def _interrupt(job: dict[str, Any] | None) -> bool:
        if not job or job.get("state") not in Job.ACTIVE_STATES:
            return False
        job["state"] = "interrupted"
        job["error"] = "The backend stopped while this job was running."
        for s in job.get("steps", []):
            if s.get("state") == "running":
                s["state"] = "cancelled"
                s["eta_s"] = None
        return True

    # ------------------------------------------------------------- persistence
    def _write(self, run: dict[str, Any]) -> None:
        path = self.run_dir(run["id"]) / "run.json"
        if not path.parent.is_dir():
            return  # deleted meanwhile
        tmp = path.with_name(f"run.json.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(run, indent=2), encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: reader has the file open
                time.sleep(0.05 * (attempt + 1))
        tmp.unlink(missing_ok=True)
        log.warning("Could not write %s", path)

    def save(self, run_id: str, force: bool = True) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            now = time.time()
            if not force and now - self._last_save.get(run_id, 0.0) < 1.0:
                return
            job = self._jobs.get(run_id)
            if job is not None:
                run["job"] = job.to_dict()
            live = self._live_jobs.get(run_id)
            if live is not None:
                run["live_job"] = live.to_dict()
            run["updated_at"] = utc_now_iso()
            self._write(run)
            self._last_save[run_id] = now

    # ------------------------------------------------------------- CRUD
    def _new_id(self, name: str) -> str:
        base = f"{datetime.now():%Y%m%d-%H%M%S}-{slugify(name)}"
        run_id, n = base, 2
        while run_id in self._runs or self.run_dir(run_id).exists():
            run_id = f"{base}-{n}"
            n += 1
        return run_id

    def create(
        self,
        *,
        name: str,
        source: dict[str, Any],
        files: dict[str, dict[str, Any]],
        ground_truth: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._lock:
            run_id = self._new_id(name)
            used: set[str] = {"run.json"}
            run_files: dict[str, dict[str, Any]] = {}
            for role in ROLES:
                f = files.get(role)
                if not f:
                    continue
                local = safe_filename(f["name"])
                if local.lower() in used:
                    local = f"{role}_{local}"
                used.add(local.lower())
                run_files[role] = {**f, "local_name": local, "status": "pending", "received": 0}
            now = utc_now_iso()
            run = {
                "schema": 1,
                "id": run_id,
                "name": name.strip(),
                "created_at": now,
                "updated_at": now,
                "source": source,
                "files": run_files,
                "ground_truth": ground_truth,
                "status": "created",
                "error": None,
                "job": None,
                "validation": None,
            }
            self.run_dir(run_id).mkdir(parents=True, exist_ok=False)
            self._runs[run_id] = run
            self._write(run)
            return copy.deepcopy(run)

    def exists(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._runs

    def get(self, run_id: str) -> dict[str, Any]:
        if not RUN_ID_RE.match(run_id or ""):
            raise AppError("Invalid run id", code="bad_run_id", status=400)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise AppError(f"Run '{run_id}' not found", code="run_not_found", status=404)
            out = copy.deepcopy(run)
            job = self._jobs.get(run_id)
            live = self._live_jobs.get(run_id)
        if job is not None:
            out["job"] = job.to_dict()
        if live is not None:
            out["live_job"] = live.to_dict()
        return out

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._runs)
        runs = []
        for run_id in ids:
            try:
                runs.append(self.get(run_id))
            except AppError:
                continue  # deleted meanwhile
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs

    def update(self, run_id: str, *, persist: bool = True, **fields: Any) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.update(fields)
            if persist:
                self.save(run_id, force=True)

    def update_file(self, run_id: str, role: str, *, persist: bool = True, **fields: Any) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or role not in run["files"]:
                return
            run["files"][role].update(fields)
            if persist:
                self.save(run_id, force=True)

    # ------------------------------------------------------------- jobs
    def attach_job(self, run_id: str, job: Job, *, live: bool = False) -> None:
        with self._lock:
            (self._live_jobs if live else self._jobs)[run_id] = job
            job.on_change = lambda j, force: self.save(run_id, force=force)
            self.save(run_id, force=True)

    def job(self, run_id: str, *, live: bool = False) -> Job | None:
        with self._lock:
            return (self._live_jobs if live else self._jobs).get(run_id)

    # ------------------------------------------------------------- delete
    def delete(self, run_id: str) -> None:
        self.get(run_id)  # validates id + existence
        with self._lock:
            self._runs.pop(run_id, None)
            self._jobs.pop(run_id, None)
            self._live_jobs.pop(run_id, None)
            self._last_save.pop(run_id, None)
        _rmtree(self.cache_dir(run_id))
        _rmtree(self.run_dir(run_id))
