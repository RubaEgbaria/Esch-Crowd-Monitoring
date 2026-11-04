"""High-level operations on runs, used by the HTTP routers."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .drive import DriveService
from .errors import AppError
from .gt import check_segments, normalize_ground_truth
from .jobs import Job, JobRunner
from .params import normalize_params
from .processing import Processor, mode_steps, process_steps
from .runs import REQUIRED_ROLES, ROLE_LABELS, ROLES, RunStore
from .schemas import CreateRunIn, PatchRunIn
from .settings import Settings
from .system import system_info, system_info_cached
from .validation import first_error, validate_run

log = logging.getLogger(__name__)

MAX_CHUNK_BYTES = 64 * 1024 * 1024


class Services:
    def __init__(self, settings: Settings) -> None:
        settings.ensure_dirs()
        self.settings = settings
        self.store = RunStore(settings)
        self.runner = JobRunner()
        self.drive = DriveService(settings)
        self.processor = Processor(settings, self.store)
        self._upload_locks: dict[str, threading.Lock] = {}
        self._upload_locks_guard = threading.Lock()

    def start(self) -> None:
        self.runner.start()
        # importing torch takes a few seconds: warm the device info up in the background
        threading.Thread(target=system_info, name="system-info", daemon=True).start()

    def stop(self) -> None:
        self.runner.stop()

    # ================================================================ create
    def create_run(self, body: CreateRunIn) -> dict[str, Any]:
        gt = normalize_ground_truth(body.ground_truth.model_dump() if body.ground_truth else None)

        if body.source == "drive":
            if not body.drive_folder or not body.drive_files:
                raise AppError("Choose a Google Drive folder and its files first.", code="bad_request", status=422)
            files_in = body.drive_files
            self._require_roles(files_in)
            files = {role: {"name": f.name, "size": f.size, "drive_id": f.id} for role, f in files_in.items()}
            source = {"kind": "drive", **body.drive_folder.model_dump()}
            self.drive.credentials()  # fail fast if not signed in
            run = self.store.create(name=body.name, source=source, files=files, ground_truth=gt)
            self._start_job(run["id"], ingest=True)
            return self.store.get(run["id"])

        if not body.upload_files:
            raise AppError("Choose the files to upload first.", code="bad_request", status=422)
        self._require_roles(body.upload_files)
        files = {role: {"name": f.name, "size": f.size} for role, f in body.upload_files.items()}
        run = self.store.create(name=body.name, source={"kind": "upload"}, files=files, ground_truth=gt)
        run_id = run["id"]
        job = self._new_job(run, ingest=True)
        self.store.attach_job(run_id, job)
        self.store.update(run_id, status="uploading")
        job.start_step("upload", "Waiting for the browser to send the files",
                       total=sum(f["size"] for f in files.values()), unit="bytes")
        return self.store.get(run_id)

    @staticmethod
    def _require_roles(files: dict[str, Any]) -> None:
        for role in REQUIRED_ROLES:
            if role not in files:
                raise AppError(f"The {ROLE_LABELS[role]} is required.", code="missing_file", status=422)
        for role in files:
            if role not in ROLES:
                raise AppError(f"Unknown file role '{role}'.", code="bad_request", status=422)

    # ================================================================ jobs
    def _new_job(self, run: dict[str, Any], *, ingest: bool) -> Job:
        """A job = [download | upload, validate] (if ingest) + the processing steps."""
        steps: list[tuple[str, str]] = []
        if ingest:
            drive = run["source"]["kind"] == "drive"
            steps.append(("download", "Download from Google Drive") if drive else ("upload", "Upload files"))
            steps.append(("validate", "Validate inputs"))
        steps += process_steps(run)
        job = Job(run["id"], "run" if ingest else "process", steps)
        job.set_weights(Processor.estimate_weights(run, device_is_gpu=system_info_cached().get("gpu", False)))
        return job

    def _start_job(self, run_id: str, *, ingest: bool) -> None:
        run = self.store.get(run_id)
        job = self._new_job(run, ingest=ingest)
        self.store.attach_job(run_id, job)
        if ingest and run["source"]["kind"] == "upload":
            job.finish_step("upload", "Files already uploaded", state="skipped")
        self.store.update(run_id, status="queued", error=None)
        self._submit(run_id, job, ingest=ingest)

    def _submit(self, run_id: str, job: Job, *, ingest: bool) -> None:
        self.runner.submit(job, lambda j: self._work(run_id, j, ingest=ingest),
                           on_finish=lambda j: self._on_job_finish(run_id, j))

    def _work(self, run_id: str, job: Job, *, ingest: bool) -> None:
        if ingest:
            self._ingest(run_id, job)
            # better estimates now that the inputs are known (frames, durations)
            job.set_weights(Processor.estimate_weights(self.store.get(run_id),
                                                       device_is_gpu=system_info_cached().get("gpu", False)))
        job.check_cancelled()
        self.store.update(run_id, status="processing")
        summary = self.processor.process(run_id, job)
        self.store.update(run_id, results=summary)

    def _ingest(self, run_id: str, job: Job) -> None:
        run = self.store.get(run_id)
        if run["source"]["kind"] == "drive":
            self.store.update(run_id, status="downloading")
            self._download_all(run_id, job)
        job.check_cancelled()

        self.store.update(run_id, status="validating")
        job.start_step("validate", "Checking the LiDAR recording")
        report = validate_run(
            self.store.run_dir(run_id),
            self.store.get(run_id),
            on_progress=lambda p, msg: job.update_step("validate", progress=p, message=msg),
        )
        self.store.update(run_id, validation=report)
        if not report["ok"]:
            job.finish_step("validate", first_error(report), state="error")
            raise AppError(first_error(report), code="validation_failed", status=422)
        n_warn = sum(len(report[k]["warnings"]) for k in ("lidar_zip", "camera_video", "lidar_screen", "ground_truth")
                     if report.get(k))
        job.finish_step("validate", "All inputs are valid" + (f" ({n_warn} warning(s))" if n_warn else ""))

    def _download_all(self, run_id: str, job: Job) -> None:
        run = self.store.get(run_id)
        run_dir = self.store.run_dir(run_id)
        items = list(run["files"].items())
        total = sum((f.get("size") or 0) for _, f in items)
        job.start_step("download", "Starting download", total=total or None, unit="bytes")
        done_before = 0
        for role, f in items:
            job.check_cancelled()
            dest = run_dir / f["local_name"]
            size = f.get("size")
            if dest.is_file() and (size is None or dest.stat().st_size == size):
                done_before += dest.stat().st_size
                job.update_step("download", done=done_before, message=f"{f['name']} is already downloaded")
                self.store.update_file(run_id, role, status="ready", received=dest.stat().st_size)
                continue
            self.store.update_file(run_id, role, status="transferring")
            base = done_before

            def on_progress(n: int, base=base, name=f["name"]) -> None:
                job.update_step("download", done=base + n, message=f"Downloading {name}")

            try:
                self.drive.download(f["drive_id"], dest, size, on_progress, job.cancel_event, f["name"])
            except AppError:
                self.store.update_file(run_id, role, status="error")
                raise
            got = dest.stat().st_size
            self.store.update_file(run_id, role, status="ready", received=got)
            done_before += got
        job.finish_step("download", f"{len(items)} file(s) downloaded")

    def _on_job_finish(self, run_id: str, job: Job) -> None:
        if not self.store.exists(run_id):
            return
        if job.state == "done":
            self.store.update(run_id, status="processed", error=None)
        elif job.state == "cancelled":
            self.store.update(run_id, status="cancelled", error="Cancelled by the user")
        else:
            failed = job.to_dict()["failed_step"]
            msg = job.error or "Unknown error"
            if failed and not msg.startswith(failed):
                msg = f"{failed}: {msg}"
            self.store.update(run_id, status="error", error=msg)

    # ================================================================ upload
    def _upload_lock(self, run_id: str) -> threading.Lock:
        with self._upload_locks_guard:
            return self._upload_locks.setdefault(run_id, threading.Lock())

    def _upload_context(self, run_id: str, role: str) -> tuple[dict[str, Any], dict[str, Any], Job]:
        run = self.store.get(run_id)
        if run["source"]["kind"] != "upload":
            raise AppError("This run gets its files from Google Drive.", code="bad_request", status=409)
        if run["status"] != "uploading":
            raise AppError("This run is not waiting for uploads.", code="not_uploading", status=409)
        f = run["files"].get(role)
        if f is None:
            raise AppError(f"This run has no {ROLE_LABELS.get(role, role)}.", code="no_file", status=404)
        job = self.store.job(run_id)
        if job is None:
            raise AppError("Upload session lost (the backend restarted). Delete the run and upload again.",
                           code="not_uploading", status=409)
        return run, f, job

    def receive_chunk(self, run_id: str, role: str, offset: int, data: bytes) -> dict[str, Any]:
        if len(data) > MAX_CHUNK_BYTES:
            raise AppError("Upload chunk too large.", code="chunk_too_large", status=413)
        with self._upload_lock(run_id):
            run, f, job = self._upload_context(run_id, role)
            if f["status"] == "ready":
                raise AppError(f"{f['name']} is already uploaded.", code="already_uploaded", status=409)
            part = self.store.run_dir(run_id) / (f["local_name"] + ".part")
            have = part.stat().st_size if part.exists() else 0
            if offset != have:
                raise AppError(f"Upload offset mismatch: the server has {have} bytes of {f['name']}.",
                               code="offset_mismatch", status=409, details={"expected_offset": have})
            if have + len(data) > f["size"]:
                raise AppError(f"{f['name']} is larger than announced ({f['size']} bytes).",
                               code="too_large", status=400)
            with open(part, "ab") as fh:
                fh.write(data)
            received = have + len(data)
            self.store.update_file(run_id, role, status="transferring", received=received, persist=False)
            total_received = sum(
                (received if r == role else x.get("received", 0)) for r, x in run["files"].items()
            )
            job.update_step("upload", done=total_received, message=f"Uploading {f['name']}")
            return {"received": received, "size": f["size"]}

    def complete_upload(self, run_id: str, role: str) -> dict[str, Any]:
        with self._upload_lock(run_id):
            run, f, _job = self._upload_context(run_id, role)
            if f["status"] != "ready":
                part = self.store.run_dir(run_id) / (f["local_name"] + ".part")
                have = part.stat().st_size if part.exists() else 0
                if have != f["size"]:
                    raise AppError(f"{f['name']} is incomplete: {have} of {f['size']} bytes received.",
                                   code="incomplete", status=409, details={"expected_offset": have})
                os.replace(part, self.store.run_dir(run_id) / f["local_name"])
                self.store.update_file(run_id, role, status="ready", received=have)
        return self.store.get(run_id)

    def start_after_upload(self, run_id: str) -> dict[str, Any]:
        with self._upload_lock(run_id):
            run = self.store.get(run_id)
            if run["status"] != "uploading":
                raise AppError("This run is not waiting for uploads.", code="not_uploading", status=409)
            missing = [ROLE_LABELS[r] for r, f in run["files"].items() if f["status"] != "ready"]
            if missing:
                raise AppError(f"Upload not finished: {', '.join(missing)}.", code="incomplete", status=409)
            job = self.store.job(run_id)
            if job is None:
                raise AppError("Upload session lost (the backend restarted).", code="not_uploading", status=409)
            job.finish_step("upload", f"{len(run['files'])} file(s) uploaded")
            self.store.update(run_id, status="queued", error=None)
            self._submit(run_id, job, ingest=True)
        return self.store.get(run_id)

    # ================================================================ manage
    def rerun(self, run_id: str, *, force: bool = False) -> dict[str, Any]:
        """Analyze / Retry / Rerun.

        If the inputs are on disk and validated, only the processing steps run
        (cached steps are reused unless ``force``). Otherwise the files are
        downloaded again (Drive) and validated first.
        """
        run = self.store.get(run_id)
        job = self.store.job(run_id)
        if job is not None and job.active:
            raise AppError("This run is already in progress.", code="busy", status=409)
        run_dir = self.store.run_dir(run_id)
        on_disk = all((run_dir / f["local_name"]).is_file() for f in run["files"].values())
        validated = bool((run.get("validation") or {}).get("ok")) and on_disk
        if run["source"]["kind"] == "upload" and not on_disk:
            missing = [ROLE_LABELS[r] for r, f in run["files"].items() if not (run_dir / f["local_name"]).is_file()]
            raise AppError(
                f"The uploaded files are incomplete ({', '.join(missing)}). "
                "Delete this run and upload the files again.",
                code="incomplete", status=409)
        if run["source"]["kind"] == "drive" and not on_disk:
            self.drive.credentials()
        if force:
            (self.store.cache_dir(run_id) / "manifest.json").unlink(missing_ok=True)
        self._start_job(run_id, ingest=not validated)
        return self.store.get(run_id)

    # ================================================================ Live view
    def get_params(self, run_id: str) -> dict[str, Any]:
        return normalize_params(self.store.get(run_id).get("params"))

    def save_params(self, run_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Remember the last parameters of this run (validated)."""
        self.store.get(run_id)
        params = normalize_params(raw)
        self.store.update(run_id, params=params)
        return params

    def resolve_mode(self, run_id: str, mode: str, raw: dict[str, Any] | None) -> dict[str, Any]:
        return self.processor.resolve(run_id, mode, normalize_params(raw))

    def _check_live_free(self, run_id: str) -> None:
        live = self.store.job(run_id, live=True)
        if live is not None and live.active:
            raise AppError("Another Live-view job is running for this run.", code="busy", status=409)
        main = self.store.job(run_id)
        if main is not None and main.active:
            raise AppError("Wait for the run's processing to finish.", code="busy", status=409)

    def start_mode(self, run_id: str, mode: str, raw: dict[str, Any] | None) -> dict[str, Any]:
        """Run only what `mode` needs; instant when the result is cached."""
        params = normalize_params(raw)
        res = self.processor.resolve(run_id, mode, params)
        if not res["available"]:
            raise AppError(res["reason"], code="mode_unavailable", status=409)
        self.store.update(run_id, params=params)
        if res["cached"]:
            return {"cached": True, "resolve": res, "run": self.store.get(run_id)}
        self._check_live_free(run_id)
        run = self.store.get(run_id)
        job = Job(run_id, f"mode:{mode}", mode_steps(mode))
        job.set_weights(Processor.estimate_weights(run, device_is_gpu=system_info_cached().get("gpu", False)))
        self.store.attach_job(run_id, job, live=True)
        self.runner.submit(job, lambda j: self.processor.run_mode(run_id, mode, params, j))
        return {"cached": False, "resolve": res, "run": self.store.get(run_id)}

    def start_export(self, run_id: str, mode: str, raw: dict[str, Any] | None, roi: bool) -> dict[str, Any]:
        params = normalize_params(raw)
        res = self.processor.resolve(run_id, mode, params)
        if not res["cached"]:
            raise AppError("Run this mode with the current parameters before exporting the video.",
                           code="not_computed", status=409)
        self._check_live_free(run_id)
        run = self.store.get(run_id)
        job = Job(run_id, "export", [("render", "Render the annotated video")])
        job.set_weights(Processor.estimate_weights(run, device_is_gpu=False))
        self.store.attach_job(run_id, job, live=True)
        out: dict[str, Any] = {}

        def work(j: Job) -> None:
            out.update(self.processor.export_video(run_id, mode, params, roi, j))

        def done(j: Job) -> None:
            if j.state == "done" and out and self.store.exists(run_id):
                self.store.update(run_id, last_export=out)

        self.runner.submit(job, work, on_finish=done)
        return self.store.get(run_id)

    def cancel_live(self, run_id: str) -> dict[str, Any]:
        job = self.store.job(run_id, live=True)
        if job is None or not job.active:
            raise AppError("Nothing to cancel.", code="not_running", status=409)
        job.cancel_event.set()
        return self.store.get(run_id)

    def cancel(self, run_id: str) -> dict[str, Any]:
        self.store.get(run_id)
        job = self.store.job(run_id)
        if job is None or not job.active:
            raise AppError("Nothing to cancel.", code="not_running", status=409)
        job.cancel_event.set()
        if job.state == "created":  # upload in progress, not queued yet
            job.set_state("cancelled", "Cancelled")
            self.store.update(run_id, status="cancelled", error="Cancelled by the user")
        return self.store.get(run_id)

    def delete(self, run_id: str) -> None:
        self.store.get(run_id)
        for job in (self.store.job(run_id), self.store.job(run_id, live=True)):
            if job is not None and job.active:
                job.cancel_event.set()
                if job.state in ("queued", "running"):
                    job.done_event.wait(timeout=20)
        with self._upload_lock(run_id):
            self.store.delete(run_id)
        with self._upload_locks_guard:
            self._upload_locks.pop(run_id, None)

    def patch(self, run_id: str, body: PatchRunIn) -> dict[str, Any]:
        run = self.store.get(run_id)
        job = self.store.job(run_id)
        fields: dict[str, Any] = {}
        if body.name is not None:
            fields["name"] = body.name.strip()
        gt_changed = body.clear_ground_truth or body.ground_truth is not None
        if gt_changed:
            if job is not None and job.active:
                raise AppError("Wait for the run to finish before changing its ground truth.",
                               code="busy", status=409)
            gt = None if body.clear_ground_truth else normalize_ground_truth(body.ground_truth.model_dump())
            fields["ground_truth"] = gt
            validation = run.get("validation")
            if validation:
                cam = validation.get("camera_video")
                if gt and cam and cam["ok"]:
                    validation["ground_truth"] = check_segments(gt["segments"], cam["info"]["duration_s"])
                else:
                    validation["ground_truth"] = None
                parts = [validation.get(k) for k in ("lidar_zip", "camera_video", "lidar_screen", "ground_truth")]
                validation["ok"] = all(p["ok"] for p in parts if p is not None)
                fields["validation"] = validation
                if run["status"] in ("ready", "error") and validation["ok"] != (run["status"] == "ready"):
                    fields["status"] = "ready" if validation["ok"] else "error"
                    fields["error"] = None if validation["ok"] else first_error(validation)
        if fields:
            self.store.update(run_id, **fields)
        return self.store.get(run_id)
