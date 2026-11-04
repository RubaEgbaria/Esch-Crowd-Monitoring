"""HTTP API: upload flow, errors, delete, restart behaviour, Drive status."""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import Services
from conftest import real_baseline_inputs

ACTIVE = {"uploading", "queued", "downloading", "validating", "processing"}


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def wait_done(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] not in ACTIVE:
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def upload(client, run_id, role, data: bytes, chunk=7):
    off = 0
    while off < len(data):
        r = client.put(f"/api/runs/{run_id}/files/{role}/chunk", params={"offset": off},
                       content=data[off:off + chunk])
        assert r.status_code == 200, r.text
        off += len(data[off:off + chunk])
    r = client.post(f"/api/runs/{run_id}/files/{role}/complete")
    assert r.status_code == 200, r.text


def create_upload_run(client, files: dict[str, bytes], gt=None, name="test run"):
    body = {"name": name, "source": "upload",
            "upload_files": {role: {"name": n, "size": len(d)} for role, (n, d) in files.items()}}
    if gt:
        body["ground_truth"] = gt
    r = client.post("/api/runs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_presets(client):
    assert client.get("/api/health").json()["status"] == "ok"
    p = client.get("/api/presets").json()
    assert {g["key"] for g in p["ground_truth"]} == {"baseline", "with_items", "lights_off", "less_crowded"}
    assert p["defaults"]["bg_dist"] == 0.15 and p["defaults"]["smooth_window"] == 8


def test_upload_flow_reports_clear_validation_errors(client, settings):
    files = {"lidar_zip": ("rec.zip", b"not a zip at all"), "camera_video": ("raw-vid.mp4", b"\x00" * 64)}
    run = create_upload_run(client, files, gt={"preset": "baseline", "segments": [
        {"start": 0, "end": 5, "people": 5}, {"start": 5, "end": "T-4", "people": 6},
        {"start": "T-4", "end": "T", "people": 5}]})
    assert run["status"] == "uploading"
    assert run["job"]["steps"][0]["key"] == "upload"
    for role, (_, data) in files.items():
        upload(client, run["id"], role, data)
    r = client.post(f"/api/runs/{run['id']}/start")
    assert r.status_code == 200, r.text

    run = wait_done(client, run["id"])
    assert run["status"] == "error"
    assert "not a valid .zip" in run["error"]
    v = run["validation"]
    assert v["ok"] is False and v["lidar_zip"]["errors"] and v["camera_video"]["errors"]
    steps = run["job"]["steps"]
    assert [s["key"] for s in steps] == ["upload", "validate", "extract", "lidar", "yolo",
                                         "transcode_camera", "align", "fusion"]
    assert [s["state"] for s in steps] == ["done", "error"] + ["pending"] * 6
    assert run["job"]["failed_step"] == "Validate inputs"
    assert (settings.runs_dir / run["id"] / "rec.zip").is_file()


def test_offset_mismatch_and_incomplete_upload(client):
    run = create_upload_run(client, {"lidar_zip": ("rec.zip", b"0123456789"), "camera_video": ("v.mp4", b"abc")})
    rid = run["id"]
    r = client.put(f"/api/runs/{rid}/files/lidar_zip/chunk", params={"offset": 5}, content=b"56789")
    assert r.status_code == 409
    assert r.json()["error"]["details"]["expected_offset"] == 0
    r = client.post(f"/api/runs/{rid}/start")
    assert r.status_code == 409 and "Upload not finished" in r.json()["error"]["message"]
    r = client.put(f"/api/runs/{rid}/files/lidar_zip/chunk", params={"offset": 0}, content=b"0123456789XYZ")
    assert r.status_code == 400  # larger than announced


def test_invalid_ground_truth_is_rejected(client):
    r = client.post("/api/runs", json={
        "name": "x", "source": "upload",
        "upload_files": {"lidar_zip": {"name": "a.zip", "size": 1}, "camera_video": {"name": "b.mp4", "size": 1}},
        "ground_truth": {"segments": [{"start": 0, "end": "X-4", "people": 5}]},
    })
    assert r.status_code == 422
    assert "Segment 1" in r.json()["error"]["message"]


def test_missing_required_file_is_rejected(client):
    r = client.post("/api/runs", json={"name": "x", "source": "upload",
                                       "upload_files": {"lidar_zip": {"name": "a.zip", "size": 1}}})
    assert r.status_code == 422 and "Camera video" in r.json()["error"]["message"]


def test_delete_run(client, settings):
    run = create_upload_run(client, {"lidar_zip": ("rec.zip", b"x"), "camera_video": ("v.mp4", b"y")})
    assert (settings.runs_dir / run["id"]).is_dir()
    assert client.delete(f"/api/runs/{run['id']}").status_code == 204
    assert not (settings.runs_dir / run["id"]).exists()
    assert client.get(f"/api/runs/{run['id']}").status_code == 404
    assert client.get("/api/runs").json() == []


def test_restart_marks_active_runs_interrupted(client, settings):
    run = create_upload_run(client, {"lidar_zip": ("rec.zip", b"x"), "camera_video": ("v.mp4", b"y")})
    restarted = Services(settings)
    again = restarted.store.get(run["id"])
    assert again["status"] == "interrupted" and "Rerun" in again["error"]


def test_bad_run_id(client):
    assert client.get("/api/runs/..%2F..%2Fsecrets").status_code in (400, 404)


def test_drive_status_without_client_file(client):
    st = client.get("/api/drive/status").json()
    assert st["client_configured"] is False and "README" in st["client_message"]
    assert st["signed_in"] is False
    r = client.post("/api/drive/signin")
    assert r.status_code == 409
    r = client.post("/api/runs", json={
        "name": "d", "source": "drive",
        "drive_folder": {"id": "abcdefghij", "name": "baseline"},
        "drive_files": {"lidar_zip": {"id": "aaaaaaaaaa", "name": "a.zip", "size": 1},
                        "camera_video": {"id": "bbbbbbbbbb", "name": "b.mp4", "size": 1}},
    })
    assert r.status_code == 401 and r.json()["error"]["code"] == "drive_not_signed_in"


@pytest.mark.skipif(real_baseline_inputs() is None,
                    reason="put the baseline Qb2 .zip and raw-vid.mp4 in tests/fixtures/baseline/ to run")
def test_real_upload_validates(client):
    zip_path, video_path = real_baseline_inputs()
    files = {"lidar_zip": (zip_path.name, zip_path.read_bytes()),
             "camera_video": (video_path.name, video_path.read_bytes())}
    run = create_upload_run(client, files, name="baseline")
    for role, (_, data) in files.items():
        upload(client, run["id"], role, data, chunk=8 * 1024 * 1024)
    client.post(f"/api/runs/{run['id']}/start")
    # validation passes and processing starts; cancel it (the acceptance tests process the baseline)
    deadline = time.time() + 120
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run['id']}").json()
        if run["status"] not in ("uploading", "queued", "validating"):
            break
        time.sleep(0.1)
    assert run["validation"]["ok"], run["error"]
    assert run["status"] in ("processing", "processed"), run["status"]
    if run["status"] == "processing":
        client.post(f"/api/runs/{run['id']}/cancel")
        run = wait_done(client, run["id"], timeout=60)
        assert run["status"] == "cancelled"
