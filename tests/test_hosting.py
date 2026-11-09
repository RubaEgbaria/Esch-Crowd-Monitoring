"""Hosted mode: shared password, Drive switch, web app served by the API, seeded runs."""
import dataclasses
import json

from fastapi.testclient import TestClient

from app.main import create_app


def hosted(settings, tmp_path, **kw):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Crowd Monitoring</title>", encoding="utf-8")
    return dataclasses.replace(settings, web_dir=web, **kw)


def test_password_protects_everything_but_health(settings, tmp_path):
    s = hosted(settings, tmp_path, app_password="s3cret")
    with TestClient(create_app(s)) as c:
        assert c.get("/api/health").status_code == 200
        for path in ("/", "/api/runs", "/api/presets"):
            r = c.get(path)
            assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
        assert c.get("/", auth=("anyone", "wrong")).status_code == 401
        r = c.get("/", auth=("supervisor", "s3cret"))
        assert r.status_code == 200 and "Crowd Monitoring" in r.text   # web app served at /
        assert c.get("/api/runs", auth=("x", "s3cret")).json() == []    # API still wins over the web mount


def test_no_password_by_default(settings, tmp_path):
    with TestClient(create_app(hosted(settings, tmp_path))) as c:
        assert c.get("/").status_code == 200 and c.get("/api/runs").status_code == 200


def test_drive_can_be_turned_off(settings, tmp_path):
    with TestClient(create_app(hosted(settings, tmp_path, drive_enabled=False))) as c:
        st = c.get("/api/drive/status").json()
        assert st["enabled"] is False and "Upload" in st["client_message"]
        assert c.post("/api/drive/signin").json()["error"]["code"] == "drive_disabled"
        assert c.post("/api/drive/resolve", json={"query": "My Drive/x"}).status_code == 409


def test_seeded_runs_are_copied_once(settings, tmp_path):
    seed = tmp_path / "seed"
    run = seed / "runs" / "20260101-000000-demo"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({
        "schema": 1, "id": run.name, "name": "demo", "created_at": "2026-01-01T00:00:00Z", "status": "ready",
        "source": {"kind": "upload"}, "files": {}, "ground_truth": None, "error": None, "job": None,
        "validation": None}), encoding="utf-8")
    (seed / "cache" / run.name).mkdir(parents=True)
    (seed / "cache" / run.name / "marker.txt").write_text("cached", encoding="utf-8")
    s = hosted(settings, tmp_path, seed_dir=seed)
    with TestClient(create_app(s)) as c:
        assert [r["name"] for r in c.get("/api/runs").json()] == ["demo"]
    assert (s.cache_dir / run.name / "marker.txt").read_text(encoding="utf-8") == "cached"
    # a second start does not overwrite what the server changed meanwhile
    (s.runs_dir / run.name / "run.json").write_text(
        (s.runs_dir / run.name / "run.json").read_text(encoding="utf-8").replace('"demo"', '"renamed"'),
        encoding="utf-8")
    with TestClient(create_app(s)) as c:
        assert [r["name"] for r in c.get("/api/runs").json()] == ["renamed"]
