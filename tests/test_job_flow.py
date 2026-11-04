"""Job progress, failure reporting and Retry (no sensor data needed)."""
import time

import pytest
from fastapi.testclient import TestClient

from app import services as services_mod
from app.errors import AppError
from app.jobs import Job, JobRunner
from app.main import create_app
from app.processing import Processor


def test_overall_progress_elapsed_and_failed_step():
    job = Job("r", "process", [("a", "Step A"), ("b", "Step B")])
    job.set_weights({"a": 1.0, "b": 3.0})
    runner = JobRunner()
    runner.start()

    def work(j: Job) -> None:
        j.start_step("a", total=10, unit="frames")
        j.update_step("a", done=10)
        j.finish_step("a")
        j.start_step("b", total=100, unit="frames")
        j.update_step("b", done=50)
        raise AppError("boom")

    runner.submit(job, work)
    assert job.done_event.wait(5)
    d = job.to_dict()
    assert d["state"] == "error" and d["error"] == "boom"
    assert d["failed_step"] == "Step B"
    assert [s["state"] for s in d["steps"]] == ["done", "error"]
    assert d["progress"] == pytest.approx(0.25)          # step a = 1/4 of the weight
    assert d["elapsed_s"] is not None and d["steps"][0]["elapsed_s"] is not None
    runner.stop()


VALID = {"ok": True, "checked_at": "x", "lidar_screen": None, "ground_truth": None,
         "lidar_zip": {"ok": True, "errors": [], "warnings": [], "info": {"frames": 3}},
         "camera_video": {"ok": True, "errors": [], "warnings": [], "info": {"frames": 3, "fps": 1}}}


def test_failure_names_the_step_and_retry_skips_validation(settings, monkeypatch):
    calls = {"validate": 0, "process": 0}

    def fake_validate(*_a, **_k):
        calls["validate"] += 1
        return VALID

    def failing_process(self, run_id, job):
        calls["process"] += 1
        job.start_step("extract")
        job.finish_step("extract", "ok")
        job.start_step("lidar", total=284, unit="frames")
        job.update_step("lidar", done=10)
        raise AppError("Something specific went wrong")

    monkeypatch.setattr(services_mod, "validate_run", fake_validate)
    monkeypatch.setattr(Processor, "process", failing_process)

    with TestClient(create_app(settings)) as c:
        r = c.post("/api/runs", json={"name": "x", "source": "upload",
                                      "upload_files": {"lidar_zip": {"name": "a.zip", "size": 1},
                                                       "camera_video": {"name": "b.mp4", "size": 1}}})
        rid = r.json()["id"]
        for role in ("lidar_zip", "camera_video"):
            c.put(f"/api/runs/{rid}/files/{role}/chunk", params={"offset": 0}, content=b"x")
            c.post(f"/api/runs/{rid}/files/{role}/complete")
        c.post(f"/api/runs/{rid}/start")

        def wait():
            for _ in range(600):
                run = c.get(f"/api/runs/{rid}").json()
                if run["status"] not in ("queued", "validating", "processing"):
                    return run
                time.sleep(0.05)
            raise AssertionError("still running")

        run = wait()
        assert run["status"] == "error"
        assert run["job"]["failed_step"] == "LiDAR pipeline"
        assert run["error"] == "LiDAR pipeline: Something specific went wrong"
        states = {s["key"]: s["state"] for s in run["job"]["steps"]}
        assert states["validate"] == "done" and states["extract"] == "done" and states["lidar"] == "error"
        assert states["yolo"] == "pending"

        # Retry: inputs are valid and on disk -> processing only, no re-validation
        r = c.post(f"/api/runs/{rid}/rerun")
        assert r.status_code == 200
        assert r.json()["job"]["kind"] == "process"
        assert r.json()["job"]["steps"][0]["key"] == "extract"
        run = wait()
        assert calls == {"validate": 1, "process": 2}
        assert run["status"] == "error"
