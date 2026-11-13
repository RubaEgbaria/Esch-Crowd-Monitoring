"""Live view: parameters, per-mode runs, replay data, media and exports."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

import numpy as np
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse, Response

from pipeline.camera import filter_records
from pipeline.sync import resample_counts

from ..errors import AppError
from ..params import full_params, normalize_params, schema_payload
from ..processing import MODES
from ..services import Services
from .deps import get_services

router = APIRouter(prefix="/api", tags=["live"])


def _mode(mode: str) -> str:
    if mode not in MODES:
        raise AppError(f"Unknown mode '{mode}'.", code="bad_mode", status=404)
    return mode


@router.get("/params/schema")
def params_schema() -> list[dict]:
    return schema_payload()


@router.get("/runs/{run_id}/params")
def get_params(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.get_params(run_id)


@router.put("/runs/{run_id}/params")
def put_params(run_id: str, body: dict[str, Any] = Body(...), s: Services = Depends(get_services)) -> dict:
    return s.save_params(run_id, body)


@router.post("/runs/{run_id}/modes/{mode}/resolve")
def resolve(run_id: str, mode: str, body: dict[str, Any] = Body(default={}),
            s: Services = Depends(get_services)) -> dict:
    return s.resolve_mode(run_id, _mode(mode), body.get("params"))


@router.post("/runs/{run_id}/modes/{mode}/run")
def run_mode(run_id: str, mode: str, body: dict[str, Any] = Body(default={}),
             s: Services = Depends(get_services)) -> dict:
    return s.start_mode(run_id, _mode(mode), body.get("params"))


@router.post("/runs/{run_id}/live/cancel")
def cancel_live(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.cancel_live(run_id)


# ---------------------------------------------------------------- replay data
@router.get("/runs/{run_id}/data/yolo")
def yolo_data(run_id: str, s: Services = Depends(get_services)) -> dict:
    """Every person box (conf > 0.10) per video frame: [x1, y1, x2, y2, conf]."""
    run = s.store.get(run_id)
    y = s.processor.load_yolo(run_id, run, full_params(run.get("params")))
    return {
        "key": y["key"], "summary": y["summary"],
        "frames": [[[*d["box"], d["conf"]] for d in r["detections"]] for r in y["records"]],
        "latency_ms": [r["latency_ms"] for r in y["records"]],
    }


@router.get("/runs/{run_id}/data/lidar/{lkey}")
def lidar_data(run_id: str, lkey: str, s: Services = Depends(get_services)) -> dict:
    """Per LiDAR frame: t (s from the first frame), counts and clusters; plus the scene."""
    if not re.fullmatch(r"[0-9a-f]{16}", lkey):
        raise AppError("Bad key.", code="bad_key", status=400)
    lid = s.processor.load_lidar(run_id, lkey)
    scene = json.loads((s.store.cache_dir(run_id) / "lidar" / lkey / "scene.json").read_text(encoding="utf-8"))
    frames = [{"t": round(r["t"], 4), "raw": r["raw"], "tracked": r["tracked"], "smooth": r["smooth"],
               "latency_ms": r["latency_ms"],
               "c": [[round(c["u"], 3), round(c["v"], 3), round(c["w"], 3), round(c["d"], 3), round(c["top"], 3),
                      c["n"], c["track_id"], bool(c["confirmed"])] for c in r["clusters"]]}
              for r in lid["frames"]]
    return {"key": lkey, "summary": lid["summary"], "frames": frames, "scene": scene}


@router.get("/runs/{run_id}/data/lidar/{lkey}/points")
def lidar_points(run_id: str, lkey: str, s: Services = Depends(get_services)) -> FileResponse:
    """uint32 n_frames, uint32 offsets[n+1], int16 points (u, v, h) in cm, little-endian."""
    if not re.fullmatch(r"[0-9a-f]{16}", lkey):
        raise AppError("Bad key.", code="bad_key", status=400)
    s.store.get(run_id)
    p = s.store.cache_dir(run_id) / "lidar" / lkey / "points.bin"
    if not p.is_file():
        raise AppError("These LiDAR results are not computed.", code="not_computed", status=404)
    return FileResponse(p, media_type="application/octet-stream")


@router.get("/runs/{run_id}/calibration")
def calibration(run_id: str, s: Services = Depends(get_services)) -> dict:
    s.store.get(run_id)
    return s.processor.calibration()


@router.api_route("/runs/{run_id}/media/camera", methods=["GET", "HEAD"])
def camera_media(run_id: str, s: Services = Depends(get_services)) -> FileResponse:
    run = s.store.get(run_id)
    p = s.processor.media_path(run_id, run, "camera_video")
    if p is None or not p.is_file():
        raise AppError("The camera video is not prepared yet: run Camera or Fusion first.",
                       code="not_prepared", status=404)
    return FileResponse(p, media_type="video/mp4")


# ---------------------------------------------------------------- exports
def _export_table(s: Services, run_id: str, mode: str, params: dict[str, Any]) -> tuple[dict, list[dict]]:
    res = s.processor.resolve(run_id, mode, params)
    if not res["cached"]:
        raise AppError("Run this mode with the current parameters first.", code="not_computed", status=409)
    r = res["result"]
    g = r["grid"]
    n = len(g["t"])
    yolo = g.get("yolo")
    if mode == "camera":   # camera counts follow the live confidence threshold
        run = s.store.get(run_id)
        fp = full_params(params)
        recs = filter_records(s.processor.load_yolo(run_id, run, fp)["records"], float(fp["yolo_conf"]))
        yolo = resample_counts(recs, np.array(g["t"])).tolist()
    rows = []
    for i in range(n):
        row: dict[str, Any] = {"t_s": g["t"][i]}
        if g.get("gt") is not None:
            row["gt"] = g["gt"][i]
        if mode in ("lidar", "fusion"):
            row["lidar"] = g["lidar"][i]
            row["lidar_available"] = g["valid"][i]
        if mode in ("camera", "fusion"):
            row["yolo"] = yolo[i]
        if mode == "fusion":
            row["fused_stack_gbt"] = g["fused"][i]
        rows.append(row)
    return r, rows


@router.get("/runs/{run_id}/modes/{mode}/export")
def export_results(run_id: str, mode: str, format: str = Query("csv", pattern="^(csv|json)$"),
                   params: str | None = None, s: Services = Depends(get_services)) -> Response:
    """Per-frame results of a mode (10 Hz grid on the video timeline) as CSV or JSON."""
    p = normalize_params(json.loads(params) if params else s.get_params(run_id))
    result, rows = _export_table(s, run_id, _mode(mode), p)
    name = f"{run_id}-{mode}"
    if format == "json":
        payload = {"run_id": run_id, "mode": mode, "label": result["label"], "key": result["key"],
                   "params": p, "lag": result.get("lag"), "metrics": result.get("metrics"),
                   "latency": result.get("latency"), "cv": {k: v for k, v in (result.get("cv") or {}).items()
                                                             if k != "oof_all"} or None,
                   "grid_hz": result["grid_hz"], "rows": rows}
        return Response(json.dumps(payload, indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["t_s"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.post("/runs/{run_id}/modes/{mode}/export-video")
def export_video(run_id: str, mode: str, body: dict[str, Any] = Body(default={}),
                 s: Services = Depends(get_services)) -> dict:
    return s.start_export(run_id, _mode(mode), body.get("params"), bool(body.get("roi", True)))


@router.get("/runs/{run_id}/exports/{name}")
def download_export(run_id: str, name: str, s: Services = Depends(get_services)) -> FileResponse:
    s.store.get(run_id)
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.mp4", name) or ".." in name:
        raise AppError("Bad file name.", code="bad_name", status=400)
    p = s.store.cache_dir(run_id) / "exports" / name
    if not p.is_file():
        raise AppError("Export not found.", code="not_found", status=404)
    return FileResponse(p, media_type="video/mp4", filename=name)
