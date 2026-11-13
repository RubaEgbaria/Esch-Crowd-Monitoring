"""Background jobs with per-step progress and ETA.

The work done for a run (download or upload, validation and, from Phase 2,
processing) is one Job made of ordered Steps. A single worker thread runs
queued jobs one after the other, so a heavy job never competes with another
one for the CPU. The API reads the job state to draw progress bars.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Any, Callable

from .errors import AppError

log = logging.getLogger(__name__)


class Cancelled(Exception):
    """Raised inside a job when the user cancels it or deletes the run."""


class Step:
    __slots__ = (
        "key", "label", "state", "progress", "done", "total", "unit",
        "message", "eta_s", "started_at", "finished_at",
    )

    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label
        self.state = "pending"  # pending | running | done | error | skipped | cancelled
        self.progress: float | None = None
        self.done: float | None = None
        self.total: float | None = None
        self.unit: str | None = None  # "bytes" | "frames" | None
        self.message = ""
        self.eta_s: float | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None

    def fraction(self) -> float:
        if self.state in ("done", "skipped"):
            return 1.0
        if self.state == "running":
            return self.progress or 0.0
        return 0.0

    def to_dict(self, now: float | None = None) -> dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__slots__}
        now = now or time.time()
        d["elapsed_s"] = None if self.started_at is None else (self.finished_at or now) - self.started_at
        return d


class Job:
    """Progress of one run's background work.

    States: created -> queued -> running -> done | error | cancelled.
    ``created`` is used for upload jobs, whose first step is driven by the
    browser sending chunks before the job is queued.
    """

    ACTIVE_STATES = ("created", "queued", "running")

    def __init__(self, run_id: str, kind: str, steps: list[tuple[str, str]]) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.run_id = run_id
        self.kind = kind
        self.state = "created"
        self.error: str | None = None
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.steps = [Step(k, label) for k, label in steps]
        # Expected seconds per step, for the overall progress bar (default 1).
        self.weights: dict[str, float] = {}
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self._lock = threading.Lock()
        self.on_change: Callable[[Job, bool], None] | None = None

    # ------------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        return self.state in self.ACTIVE_STATES

    def _step(self, key: str) -> Step:
        for s in self.steps:
            if s.key == key:
                return s
        raise KeyError(key)

    def _changed(self, force: bool = False) -> None:
        # Never call while holding self._lock (the store locks itself, then us).
        if self.on_change is not None:
            self.on_change(self, force)

    def set_state(self, state: str, error: str | None = None) -> None:
        with self._lock:
            self.state = state
            if error is not None:
                self.error = error
            now = time.time()
            if state == "running" and self.started_at is None:
                self.started_at = now
            if state in ("done", "error", "cancelled"):
                self.finished_at = now
                for s in self.steps:
                    if s.state == "running":
                        s.state = "error" if state == "error" else "cancelled"
                        s.finished_at = now
                        s.eta_s = None
        self._changed(force=True)

    # ------------------------------------------------------------------ steps
    def start_step(
        self,
        key: str,
        message: str = "",
        *,
        total: float | None = None,
        unit: str | None = None,
    ) -> None:
        with self._lock:
            s = self._step(key)
            s.state = "running"
            s.started_at = time.time()
            s.finished_at = None
            s.message = message
            s.total = total
            s.unit = unit
            s.done = 0 if total is not None else None
            s.progress = 0.0 if total else None
            s.eta_s = None
        self._changed(force=True)

    def update_step(
        self,
        key: str,
        *,
        done: float | None = None,
        total: float | None = None,
        progress: float | None = None,
        message: str | None = None,
    ) -> None:
        with self._lock:
            s = self._step(key)
            if total is not None:
                s.total = total
            if done is not None:
                s.done = done
            if progress is None and s.done is not None and s.total:
                progress = s.done / s.total
            if progress is not None:
                s.progress = max(0.0, min(1.0, float(progress)))
                elapsed = time.time() - (s.started_at or time.time())
                if 0.005 < s.progress < 1.0 and elapsed > 1.0:
                    s.eta_s = elapsed * (1.0 - s.progress) / s.progress
            if message is not None:
                s.message = message
        self._changed()

    def finish_step(self, key: str, message: str | None = None, *, state: str = "done") -> None:
        with self._lock:
            s = self._step(key)
            s.state = state
            s.finished_at = time.time()
            s.eta_s = None
            if state == "done":
                s.progress = 1.0
                if s.total is not None:
                    s.done = s.total
            if message is not None:
                s.message = message
        self._changed(force=True)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def set_weights(self, weights: dict[str, float]) -> None:
        with self._lock:
            self.weights = {k: max(0.05, float(v)) for k, v in weights.items()}

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            weights = [self.weights.get(s.key, 1.0) for s in self.steps]
            total = sum(weights) or 1.0
            overall = sum(w * s.fraction() for w, s in zip(weights, self.steps)) / total
            start = self.started_at or self.created_at
            elapsed = (self.finished_at or now) - start
            eta = None
            if self.state == "running" and 0.02 < overall < 1.0 and elapsed > 2.0:
                eta = elapsed * (1.0 - overall) / overall
            return {
                "id": self.id,
                "kind": self.kind,
                "state": self.state,
                "error": self.error,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_s": elapsed,
                "progress": overall,
                "eta_s": eta,
                "failed_step": next((s.label for s in self.steps if s.state == "error"), None),
                "steps": [s.to_dict(now) for s in self.steps],
            }


class JobRunner:
    """Runs submitted jobs one at a time on a daemon thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._queue.put(None)

    def submit(
        self,
        job: Job,
        fn: Callable[[Job], None],
        on_finish: Callable[[Job], None] | None = None,
    ) -> None:
        job.set_state("queued")
        self._queue.put((job, fn, on_finish))

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            job, fn, on_finish = item
            self._run(job, fn)
            if on_finish is not None:
                try:
                    on_finish(job)
                except Exception:  # pragma: no cover - defensive
                    log.exception("on_finish failed for job %s", job.id)
            job.done_event.set()

    @staticmethod
    def _run(job: Job, fn: Callable[[Job], None]) -> None:
        if job.cancel_event.is_set():
            job.set_state("cancelled", "Cancelled before it started")
            return
        job.set_state("running")
        try:
            fn(job)
        except Cancelled:
            job.set_state("cancelled", "Cancelled")
        except AppError as e:
            job.set_state("error", e.message)
        except Exception as e:  # unexpected: keep the message, log the trace
            log.exception("Job %s failed", job.id)
            job.set_state("error", f"Unexpected error: {e}")
        else:
            job.set_state("done")
