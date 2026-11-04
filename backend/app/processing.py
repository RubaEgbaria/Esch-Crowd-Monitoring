"""Processing: per-mode runs (LiDAR only, Camera only, Fusion), Analyze, video export.

Building blocks, each cached in ``cache/<run_id>/`` so nothing is computed twice:
  extract            cache/extracted/              key: the zip
  LiDAR pipeline     cache/lidar/<lidar_key>/      key: zip + LiDAR parameters
  YOLO               cache/yolo/detections.json    key: video + model (boxes at conf > 0.10)
  H.264 videos       cache/media/camera.mp4, lidar_screen.mp4
  mode results       cache/modes/<mode>-<key>.json key: mode + every parameter it uses
Nothing is ever replaced by synthetic data: a failing step stops the job with
a clear message.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.camera import ensure_model, filter_records, roi_polygon_px, run_yolo, select_device
from pipeline.config import ALIGN_CONF, CALIBRATION
from pipeline.fusion import FUSION_METHODS, LEARNED_METHODS, evaluate
from pipeline.lidar import (build_scene, lidar_params, run_frames, smooth_counts, voxel_downsample,
                           zone_footprint_floor, zone_tilt_deg)
from pipeline.metrics import counting_metrics
from pipeline.qb2_io import find_recording, load_reference
from pipeline.render import render_video
from pipeline.sync import estimate_lag, make_grid, place_lidar, resample_counts, resolve_segments, sample_gt

from .errors import AppError
from .jobs import Cancelled, Job
from .params import full_params
from .runs import RunStore, utc_now_iso
from .settings import Settings
from .validation import BROWSER_CODECS

log = logging.getLogger(__name__)

PIPELINE_VERSION = 2   # bump when the meaning of a cached result changes
MODES = ("lidar", "camera", "fusion")
MODE_LABELS = {"lidar": "LiDAR only", "camera": "Camera only (YOLO11m)",
               "fusion": "Fusion (LiDAR + Camera, Stack-GBT)"}
FUSION_METHOD = "Stack-GBT"

STEP_LABELS = {
    "extract": "Extract the LiDAR zip",
    "lidar": "LiDAR pipeline",
    "yolo": "YOLO11m detection",
    "transcode_camera": "Camera video → H.264",
    "transcode": "Sensor UI recording → H.264",
    "lidar_results": "Time alignment and metrics",
    "camera_results": "Counts and metrics",
    "align": "Time alignment",
    "fusion": "Fusion: Stack-GBT, blocked CV",
    "render": "Render the annotated video",
}

MODE_STEPS = {
    "lidar": ["extract", "lidar", "lidar_results"],
    "camera": ["yolo", "transcode_camera", "camera_results"],
    "fusion": ["extract", "lidar", "yolo", "transcode_camera", "align", "fusion"],
}


def process_steps(run: dict[str, Any]) -> list[tuple[str, str]]:
    """Steps of Analyze (everything)."""
    keys = ["extract", "lidar", "yolo", "transcode_camera"]
    if "lidar_screen" in run["files"]:
        keys.append("transcode")
    keys += ["align", "fusion"]
    return [(k, STEP_LABELS[k]) for k in keys]


def mode_steps(mode: str) -> list[tuple[str, str]]:
    return [(k, STEP_LABELS[k]) for k in MODE_STEPS[mode]]


def _fingerprint(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"name": path.name, "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _key(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _nan_to_none(a, digits: int | None = None) -> list:
    out = []
    for x in np.asarray(a, dtype=float):
        if np.isnan(x):
            out.append(None)
        else:
            out.append(round(float(x), digits) if digits is not None else float(x))
    return out


def _metrics(pred: np.ndarray, gt: np.ndarray, window: str) -> dict[str, Any]:
    m = counting_metrics(pred, gt)
    return {**{k: round(float(v), 4) for k, v in m.items()}, "n": int(len(gt)), "window": window}


def find_ffmpeg() -> tuple[str | None, str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe, "ffmpeg (system)"
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe(), "imageio-ffmpeg"
    except Exception:
        return None, "not found"


class Processor:
    def __init__(self, settings: Settings, store: RunStore) -> None:
        self.settings = settings
        self.store = store

    # ================================================================== cache helpers
    def _cache(self, run_id: str) -> Path:
        d = self.store.cache_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest(self, run_id: str) -> dict[str, Any]:
        p = self._cache(run_id) / "manifest.json"
        try:
            m = _read_json(p)
            if isinstance(m.get("steps"), dict):
                return m
        except (OSError, ValueError):
            pass
        return {"steps": {}}

    def _cached(self, run_id: str, step: str, key: str, *outputs: str) -> bool:
        entry = self._manifest(run_id)["steps"].get(step)
        cache = self._cache(run_id)
        return bool(entry and entry.get("key") == key and all((cache / o).exists() for o in outputs))

    def _mark(self, run_id: str, step: str, key: str, seconds: float) -> None:
        m = self._manifest(run_id)
        m["steps"][step] = {"key": key, "seconds": round(seconds, 2), "at": time.time()}
        _write_json(self._cache(run_id) / "manifest.json", m)

    @staticmethod
    def _video_info(run: dict[str, Any]) -> dict[str, Any]:
        cam = ((run.get("validation") or {}).get("camera_video") or {}).get("info") or {}
        if not cam.get("frames") or not cam.get("fps"):
            raise AppError("The camera video has not been validated yet.", code="not_validated", status=409)
        return {"frames": int(cam["frames"]), "fps": float(cam["fps"]),
                "width": int(cam.get("width") or 0), "height": int(cam.get("height") or 0),
                # sensors_fusion.ipynb cell 5: T = total_frames / fps
                "T": float(cam["frames"]) / float(cam["fps"])}

    @staticmethod
    def estimate_weights(run: dict[str, Any], device_is_gpu: bool) -> dict[str, float]:
        """Expected seconds per step, for the overall progress bar."""
        v = run.get("validation") or {}
        lid = (v.get("lidar_zip") or {}).get("info", {})
        cam = (v.get("camera_video") or {}).get("info", {})
        scr = (v.get("lidar_screen") or {}).get("info", {})
        zip_mb = (run["files"]["lidar_zip"].get("size") or 0) / 1e6
        return {
            "download": max(1.0, sum((f.get("size") or 0) for f in run["files"].values()) / 5e6),
            "upload": max(1.0, sum((f.get("size") or 0) for f in run["files"].values()) / 50e6),
            "validate": 2.0,
            "extract": max(0.5, zip_mb / 150),
            "lidar": max(1.0, lid.get("frames", 300) * 0.02),
            "yolo": max(2.0, cam.get("frames", 450) * (0.03 if device_is_gpu else 0.4)),
            "transcode_camera": max(1.0, cam.get("duration_s", 30) * 0.08),
            "transcode": max(1.0, scr.get("duration_s", 30) * 0.08),
            "lidar_results": 0.3, "camera_results": 0.3, "align": 0.3,
            "fusion": 4.0 if run.get("ground_truth") else 0.3,
            "render": max(2.0, cam.get("frames", 450) * 0.02),
        }

    def _gt(self, run: dict[str, Any], T: float):
        gt = run.get("ground_truth")
        if not gt:
            return None
        return resolve_segments([(s["start"], s["end"], s["people"]) for s in gt["segments"]], T)

    # ================================================================== keys
    def extract_key(self, run_id: str, run: dict[str, Any]) -> str:
        zip_path = self.store.run_dir(run_id) / run["files"]["lidar_zip"]["local_name"]
        return _key({"zip": _fingerprint(zip_path), "v": 1})

    def lidar_key(self, run_id: str, run: dict[str, Any], params: dict[str, Any]) -> str:
        return _key({"extract": self.extract_key(run_id, run), "params": lidar_params(params), "v": 2})

    def yolo_key(self, run_id: str, run: dict[str, Any], params: dict[str, Any]) -> str:
        video = self.store.run_dir(run_id) / run["files"]["camera_video"]["local_name"]
        return _key({"video": _fingerprint(video), "model": params["yolo_model"],
                     "conf": float(params["yolo_store_conf"]), "imgsz": int(params["yolo_imgsz"]), "v": 1})

    def yolo_ready(self, run_id: str, run: dict[str, Any], params: dict[str, Any]) -> bool:
        return self._cached(run_id, "yolo", self.yolo_key(run_id, run, params), "yolo/detections.json")

    def lidar_ready(self, run_id: str, lkey: str) -> bool:
        return (self._cache(run_id) / "lidar" / lkey / "frames.json").is_file()

    def lag_spec(self, run_id: str, run: dict[str, Any], params: dict[str, Any], *, yolo_will_exist: bool = False) -> dict:
        """How the LiDAR is placed on the video timeline."""
        if params.get("lidar_offset_s") is not None:
            return {"source": "manual", "lag_s": float(params["lidar_offset_s"])}
        if yolo_will_exist or self.yolo_ready(run_id, run, params):
            return {"source": "auto", "yolo": self.yolo_key(run_id, run, params), "conf": ALIGN_CONF,
                    "max_lag_s": float(params["max_lag_s"])}
        return {"source": "none"}

    def mode_key(self, run_id: str, run: dict[str, Any], mode: str, params: dict[str, Any]) -> str:
        base = {"mode": mode, "v": PIPELINE_VERSION, "gt": run.get("ground_truth"), "grid_hz": params["grid_hz"]}
        if mode == "lidar":
            base.update(lidar=self.lidar_key(run_id, run, params), lag=self.lag_spec(run_id, run, params))
        elif mode == "camera":
            # no confidence: the browser filters the stored boxes instantly
            base.update(yolo=self.yolo_key(run_id, run, params))
        else:
            base.update(lidar=self.lidar_key(run_id, run, params), yolo=self.yolo_key(run_id, run, params),
                        lag=self.lag_spec(run_id, run, params, yolo_will_exist=True),
                        conf=float(params["yolo_conf"]), folds=int(params["cv_folds"]))
        return _key(base)

    def _mode_path(self, run_id: str, mode: str, key: str) -> Path:
        return self._cache(run_id) / "modes" / f"{mode}-{key}.json"

    def resolve(self, run_id: str, mode: str, user_params: dict[str, Any] | None) -> dict[str, Any]:
        """Is the result of `mode` with these parameters already computed?"""
        if mode not in MODES:
            raise AppError(f"Unknown mode '{mode}'.", code="bad_mode", status=404)
        run = self.store.get(run_id)
        if not (run.get("validation") or {}).get("ok"):
            raise AppError("The inputs of this run are not validated yet.", code="not_validated", status=409)
        params = full_params(user_params)
        out: dict[str, Any] = {"mode": mode, "label": MODE_LABELS[mode], "available": True, "reason": None}
        if mode == "fusion" and not run.get("ground_truth"):
            out.update(available=False, reason="Fusion needs ground truth to train Stack-GBT. Add ground truth "
                                                "to this run to enable it.")
        key = self.mode_key(run_id, run, mode, params)
        path = self._mode_path(run_id, mode, key)
        latest = None
        if not path.is_file():
            # the most recent result of this mode (other parameters), shown as "parameters changed"
            others = sorted((self._cache(run_id) / "modes").glob(f"{mode}-*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            for p in others:
                try:
                    latest = _read_json(p)
                    break
                except (OSError, ValueError):
                    continue
        out.update(key=key, cached=path.is_file(), result=_read_json(path) if path.is_file() else None,
                   latest=latest, steps=[{"key": k, "label": label} for k, label in mode_steps(mode)])
        return out

    # ================================================================== building blocks
    def extract(self, run_id: str, run: dict[str, Any], job: Job | None) -> dict[str, Any]:
        zip_path = self.store.run_dir(run_id) / run["files"]["lidar_zip"]["local_name"]
        dest = self._cache(run_id) / "extracted"
        key = self.extract_key(run_id, run)
        t0 = time.time()
        if job:
            job.start_step("extract")
        if self._cached(run_id, "extract", key, "extracted"):
            frames, ref, zones, ds = find_recording(str(dest))
            if job:
                job.finish_step("extract", f"Already extracted ({len(frames)} frames)")
        else:
            if dest.exists():
                shutil.rmtree(dest)
            with zipfile.ZipFile(zip_path) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if job:
                    job.start_step("extract", "Extracting", total=len(members), unit="files")
                for i, m in enumerate(members, 1):
                    zf.extract(m, dest)   # zipfile strips absolute paths and ".."
                    if job and (i % 20 == 0 or i == len(members)):
                        job.check_cancelled()
                        job.update_step("extract", done=i)
            frames, ref, zones, ds = find_recording(str(dest))
            self._mark(run_id, "extract", key, time.time() - t0)
            if job:
                job.finish_step("extract", f"{len(frames)} frames extracted")
        return {"key": key, "frames": frames, "ref": ref, "zones": zones, "ds": ds}

    def lidar(self, run_id: str, run: dict[str, Any], params: dict[str, Any], job: Job | None,
              ex: dict[str, Any] | None = None) -> dict[str, Any]:
        lp = lidar_params(params)
        lkey = self.lidar_key(run_id, run, params)
        out_dir = self._cache(run_id) / "lidar" / lkey
        if job:
            job.start_step("lidar")
        if self.lidar_ready(run_id, lkey):
            data = _read_json(out_dir / "frames.json")
            if job:
                job.finish_step("lidar", f"Using cached results for these parameters ({len(data['frames'])} frames)")
            return {"key": lkey, **data}

        ex = ex or self.extract(run_id, run, None)
        t0 = time.time()
        frames = ex["frames"]
        if job:
            job.start_step("lidar", "Fitting the floor plane", total=len(frames), unit="frames")
        scene = build_scene(load_reference(ex["ref"]), ex["zones"], ex["ds"])
        records, points, offsets = [], [], [0]

        def on_progress(i: int, n: int) -> None:
            if job and (i % 5 == 0 or i == n):
                job.update_step("lidar", done=i, total=n, message="Background subtraction, DBSCAN, tracking")

        for rec in run_frames(frames, scene, lp, on_progress,
                              should_stop=job.cancel_event.is_set if job else None):
            P = rec.pop("points")
            points.append(np.round(P * 100).astype(np.int16))     # (u, v, h) in cm
            offsets.append(offsets[-1] + len(P))
            rec["n_fg"] = int(len(P))
            records.append(rec)
        if job:
            job.check_cancelled()
        if not records:
            raise AppError("The LiDAR recording has no frames.", code="no_frames")

        smooth = smooth_counts([r["tracked"] for r in records], lp["smooth_window"])
        ts = np.array([r["timestamp_ns"] for r in records], dtype=np.int64)
        # sensors_fusion.ipynb cell 8 (4.4): lidar_times = (ts_ns - ts_ns[0]) / 1e9 + offset (0 here;
        # the placement on the video timeline is the lag of the alignment).
        t = (ts - ts[0]) / 1e9
        for r, s, ti in zip(records, smooth, t):
            r["smooth"] = int(s)
            r["t"] = float(ti)
            r["latency_ms"] = round(r["latency_ms"], 3)

        out_dir.mkdir(parents=True, exist_ok=True)
        pts = np.concatenate(points) if points else np.zeros((0, 3), np.int16)
        offs = np.array(offsets, dtype=np.uint32)
        # Binary for the browser: uint32 n_frames, uint32 offsets[n+1], int16 points[(u, v, h) cm]
        with open(out_dir / "points.bin", "wb") as f:
            f.write(np.array([len(records)], dtype="<u4").tobytes())
            f.write(offs.astype("<u4").tobytes())
            f.write(pts.astype("<i2").tobytes())
        _write_json(out_dir / "scene.json", {
            "background": np.round(voxel_downsample(scene.background_f, 0.05, 15000) * 100).astype(int).tolist(),
            # The zone filter keeps a prism along the zone's z axis; its footprint is drawn at
            # 1.0 m (body height), with 0 m and 1.7 m for reference (the prism may be tilted).
            "zone": {"name": scene.zone.name,
                     "outline": np.round(zone_footprint_floor(scene.zone, scene.floor, 1.0), 3).tolist(),
                     "outlines": {str(h): np.round(zone_footprint_floor(scene.zone, scene.floor, h), 3).tolist()
                                  for h in (0.0, 1.0, 1.7)},
                     "tilt_deg": round(zone_tilt_deg(scene.zone, scene.floor), 1)},
            "floor": {"sensor_height_m": round(float(scene.floor.d_floor), 3),
                      "floor_frac": round(float(scene.floor.floor_frac), 3)},
        })
        rate = float(1.0 / np.median(np.diff(t))) if len(t) > 1 else None
        lat = np.array([r["latency_ms"] for r in records])
        summary = {
            "frames": len(records), "duration_s": round(float(t[-1]), 3),
            "rate_hz": round(rate, 2) if rate else None,
            "latency_ms_mean": round(float(lat.mean()), 2),
            "raw_mean": round(float(np.mean([r["raw"] for r in records])), 4),
            "tracked_mean": round(float(np.mean([r["tracked"] for r in records])), 4),
            "smooth_mean": round(float(np.mean(smooth)), 4),
            "smooth_median": float(np.median(smooth)),
            "sensor_height_m": round(float(scene.floor.d_floor), 3),
            "floor_frac": round(float(scene.floor.floor_frac), 3),
            "zone": scene.zone.name,
            "params": {k: list(v) if isinstance(v, tuple) else v for k, v in lp.items()},
        }
        data = {"frames": records, "summary": summary}
        _write_json(out_dir / "frames.json", data)
        if job:
            job.finish_step("lidar", f"{len(records)} frames · {summary['latency_ms_mean']:.1f} ms/frame")
        log.info("LiDAR %s for run %s in %.1fs", lkey, run_id, time.time() - t0)
        return {"key": lkey, **data}

    def load_lidar(self, run_id: str, lkey: str) -> dict[str, Any]:
        d = self._cache(run_id) / "lidar" / lkey
        if not (d / "frames.json").is_file():
            raise AppError("These LiDAR results are not computed (any more). Run the mode again.",
                           code="not_computed", status=404)
        return {"key": lkey, **_read_json(d / "frames.json")}

    def yolo(self, run_id: str, run: dict[str, Any], params: dict[str, Any], job: Job | None) -> dict[str, Any]:
        video = self.store.run_dir(run_id) / run["files"]["camera_video"]["local_name"]
        model_path = self.settings.models_dir / params["yolo_model"]
        key = self.yolo_key(run_id, run, params)
        out = self._cache(run_id) / "yolo" / "detections.json"
        if job:
            job.start_step("yolo")
        if self._cached(run_id, "yolo", key, "yolo/detections.json"):
            data = _read_json(out)
            if job:
                job.finish_step("yolo", f"Using cached detections ({data['summary']['frames']} frames, "
                                        f"{data['summary']['device']})")
            return {"key": key, **data}
        t0 = time.time()
        total = self._video_info(run)["frames"]
        if job:
            job.start_step("yolo", "Loading the model", total=total, unit="frames")
            if not model_path.is_file():
                job.update_step("yolo", message=f"Downloading the {params['yolo_model']} weights")
        ensure_model(model_path)
        device, device_label = select_device()
        if job:
            job.update_step("yolo", message=f"Running on {device_label}")
        res = run_yolo(video, model_path, conf=float(params["yolo_store_conf"]), imgsz=int(params["yolo_imgsz"]),
                       device=device, on_progress=(lambda i, n: job.update_step("yolo", done=i, total=n)) if job else None,
                       should_stop=job.cancel_event.is_set if job else None)
        if job:
            job.check_cancelled()
        if not res["records"]:
            raise AppError("No frame could be read from the camera video.", code="no_frames")
        import torch
        import ultralytics

        for r in res["records"]:
            for d in r["detections"]:
                d["box"] = [round(v, 1) for v in d["box"]]
            r["latency_ms"] = round(r["latency_ms"], 2)
        lat = np.array([r["latency_ms"] for r in res["records"]])
        summary = {
            "frames": res["frames"], "fps": res["fps"], "device": device_label, "model": params["yolo_model"],
            "imgsz": int(params["yolo_imgsz"]), "stored_conf": float(params["yolo_store_conf"]),
            "latency_ms_mean": round(float(lat.mean()), 2), "latency_ms_median": round(float(np.median(lat)), 2),
            "ultralytics": ultralytics.__version__, "torch": torch.__version__,
        }
        data = {"records": res["records"], "summary": summary}
        _write_json(out, data)
        self._mark(run_id, "yolo", key, time.time() - t0)
        if job:
            job.finish_step("yolo", f"{res['frames']} frames on {device_label} · "
                                    f"{summary['latency_ms_mean']:.0f} ms/frame")
        return {"key": key, **data}

    def load_yolo(self, run_id: str, run: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        if not self.yolo_ready(run_id, run, params):
            raise AppError("YOLO has not been run on this video yet.", code="not_computed", status=404)
        return {"key": self.yolo_key(run_id, run, params),
                **_read_json(self._cache(run_id) / "yolo" / "detections.json")}

    def transcode(self, run_id: str, run: dict[str, Any], role: str, job: Job | None, step: str) -> dict[str, Any]:
        """H.264 copy of a video for the browser (raw-vid.mp4 and lidar_top_view.mp4 are fmp4)."""
        src = self.store.run_dir(run_id) / run["files"][role]["local_name"]
        info = ((run.get("validation") or {}).get(role) or {}).get("info", {})
        codec = (info.get("codec") or "").lower()
        name = "camera.mp4" if role == "camera_video" else "lidar_screen.mp4"
        dst = self._cache(run_id) / "media" / name
        if job:
            job.start_step(step)
        if codec in BROWSER_CODECS:
            if job:
                job.finish_step(step, f"Already browser-compatible ({codec}); served as is", state="skipped")
            return {"path": "original", "codec": codec}
        key = _key({"src": _fingerprint(src), "v": 2})
        if self._cached(run_id, step, key, f"media/{name}"):
            if job:
                job.finish_step(step, "Using the cached H.264 copy")
            return {"path": "cache", "codec": "h264", "from_codec": codec}
        exe, source = find_ffmpeg()
        if not exe:
            raise AppError("ffmpeg is not available: install ffmpeg or the imageio-ffmpeg package.", code="no_ffmpeg")
        t0 = time.time()
        duration = float(info.get("duration_s") or 0)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.stem + ".part.mp4")
        # -fps_mode passthrough keeps every frame at its timestamp (frame i stays at i / fps),
        # -g 5 puts a keyframe every 5 frames for smooth scrubbing.
        cmd = [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-g", "5", "-fps_mode", "passthrough", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
               "-movflags", "+faststart", "-an", "-progress", "pipe:1", "-nostats", str(tmp)]
        if job:
            job.update_step(step, progress=0.0, message=f"{codec or 'unknown codec'} → H.264 with {source}")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_path = dst.with_suffix(".log")
        with open(log_path, "wb") as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, creationflags=flags)
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if job and job.cancel_event.is_set():
                        proc.kill()
                        raise Cancelled()
                    line = raw.decode(errors="replace").strip()
                    if job and line.startswith("out_time_us=") and duration > 0:
                        try:
                            job.update_step(step, progress=min(0.99, int(line.split("=", 1)[1]) / 1e6 / duration))
                        except ValueError:
                            pass
                code = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
        if code != 0 or not tmp.is_file():
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-400:]
            raise AppError(f"ffmpeg could not transcode {src.name} (exit {code}): {tail}", code="transcode_failed")
        os.replace(tmp, dst)
        self._mark(run_id, step, key, time.time() - t0)
        if job:
            job.finish_step(step, f"{codec} → H.264 ({dst.stat().st_size / 1e6:.1f} MB)")
        return {"path": "cache", "codec": "h264", "from_codec": codec}

    def media_path(self, run_id: str, run: dict[str, Any], role: str) -> Path | None:
        name = "camera.mp4" if role == "camera_video" else "lidar_screen.mp4"
        p = self._cache(run_id) / "media" / name
        if p.is_file():
            return p
        codec = (((run.get("validation") or {}).get(role) or {}).get("info", {}).get("codec") or "").lower()
        if codec in BROWSER_CODECS:
            return self.store.run_dir(run_id) / run["files"][role]["local_name"]
        return None

    def calibration(self) -> dict[str, Any]:
        roi = roi_polygon_px(CALIBRATION["floor_calib_xy"], CALIBRATION["floor_calib_uv"], CALIBRATION["roi_floor_xy"])
        return {"roi_px": np.round(roi, 2).tolist(), "approximate": True, **CALIBRATION,
                "source": "sensors_fusion.ipynb, cells 2 and 7 (floor homography)"}

    # ================================================================== alignment
    def lag(self, run_id: str, run: dict[str, Any], params: dict[str, Any], lidar: dict[str, Any],
            yolo: dict[str, Any] | None, spec: dict[str, Any]) -> dict[str, Any]:
        info = self._video_info(run)
        lidar_recs = [{"t": r["t"], "count": r["smooth"]} for r in lidar["frames"]]
        base = {"source": spec["source"], "max_lag_s": float(params["max_lag_s"]), "align_conf": ALIGN_CONF,
                "lidar_duration_s": lidar["summary"]["duration_s"]}
        if spec["source"] == "manual":
            return {**base, "lag_s": spec["lag_s"], "r": None, "at_edge": False, "auto_lag_s": None,
                    "note": "Manual LiDAR offset."}
        if spec["source"] == "none" or yolo is None:
            return {**base, "lag_s": 0.0, "r": None, "at_edge": False, "auto_lag_s": None,
                    "note": "No lag estimate yet: the LiDAR is placed at t = 0 s. Run Camera or Fusion once "
                            "(the lag is then estimated automatically) or set the LiDAR offset."}
        yolo_f = filter_records(yolo["records"], ALIGN_CONF)
        est = estimate_lag(yolo_f, lidar_recs, info["T"], float(params["grid_hz"]), float(params["max_lag_s"]))
        return {**base, "lag_s": est["auto_lag_s"], "auto_lag_s": est["auto_lag_s"],
                "r": None if np.isnan(est["r"]) else round(est["r"], 4), "at_edge": est["at_edge"],
                "note": est["note"], "curve": est["curve"]}

    # ================================================================== modes
    def run_mode(self, run_id: str, mode: str, user_params: dict[str, Any] | None, job: Job) -> dict[str, Any]:
        run = self.store.get(run_id)
        params = full_params(user_params)
        if mode == "fusion" and not run.get("ground_truth"):
            raise AppError("Fusion needs ground truth.", code="no_gt", status=409)
        key = self.mode_key(run_id, run, mode, params)
        path = self._mode_path(run_id, mode, key)
        if path.is_file():
            for k, _ in mode_steps(mode):
                job.start_step(k)
                job.finish_step(k, "Cached")
            return _read_json(path)

        def step(k: str, fn):
            job.check_cancelled()
            try:
                return fn()
            except (AppError, Cancelled):
                raise
            except Exception as e:
                log.exception("Step %s failed for run %s", k, run_id)
                raise AppError(f"{STEP_LABELS[k]} failed: {type(e).__name__}: {e}", code="step_failed") from e

        if mode == "lidar":
            ex = step("extract", lambda: self.extract(run_id, run, job))
            lid = step("lidar", lambda: self.lidar(run_id, run, params, job, ex))
            job.start_step("lidar_results", "Placing the LiDAR on the video timeline")
            result = step("lidar_results", lambda: self._lidar_result(run_id, run, params, lid, key))
            job.finish_step("lidar_results", self._lag_message(result["lag"]))
        elif mode == "camera":
            yolo = step("yolo", lambda: self.yolo(run_id, run, params, job))
            step("transcode_camera", lambda: self.transcode(run_id, run, "camera_video", job, "transcode_camera"))
            job.start_step("camera_results")
            result = step("camera_results", lambda: self._camera_result(run_id, run, params, yolo, key))
            job.finish_step("camera_results", "Done")
        else:
            ex = step("extract", lambda: self.extract(run_id, run, job))
            lid = step("lidar", lambda: self.lidar(run_id, run, params, job, ex))
            yolo = step("yolo", lambda: self.yolo(run_id, run, params, job))
            step("transcode_camera", lambda: self.transcode(run_id, run, "camera_video", job, "transcode_camera"))
            job.start_step("align", "Cross-correlating the YOLO and LiDAR counts")
            spec = self.lag_spec(run_id, run, params, yolo_will_exist=True)
            lag = step("align", lambda: self.lag(run_id, run, params, lid, yolo, spec))
            job.finish_step("align", self._lag_message(lag))
            job.start_step("fusion", "Stack-GBT, blocked 5-fold CV, out-of-fold predictions")
            result = step("fusion", lambda: self._fusion_result(run_id, run, params, lid, yolo, lag, key))
            m = result["metrics"].get("Fusion (Stack-GBT)", {})
            job.finish_step("fusion", f"Stack-GBT blocked-CV MAE {result['cv']['stack_gbt_mae']:.3f} · "
                                      f"MAE on the overlap {m.get('MAE', float('nan')):.3f}")
        _write_json(path, result)
        return result

    @staticmethod
    def _lag_message(lag: dict[str, Any]) -> str:
        if lag["source"] == "manual":
            return f"Manual offset {lag['lag_s']:+.2f} s"
        if lag["source"] == "none" or lag.get("r") is None:
            return "No lag estimate yet (LiDAR at t = 0 s)" if lag["source"] == "none" else (lag.get("note") or "")
        edge = " (edge of the ±5 s window)" if lag.get("at_edge") else ""
        return f"Lag {lag['lag_s']:+.2f} s{edge}, r = {lag['r']:.2f}"

    def _base_result(self, run: dict[str, Any], mode: str, key: str, params: dict[str, Any]) -> dict[str, Any]:
        info = self._video_info(run)
        t_grid = make_grid(info["T"], float(params["grid_hz"]))
        segs = self._gt(run, info["T"])
        gt = sample_gt(t_grid, segs) if segs is not None else None
        return {
            "mode": mode, "label": MODE_LABELS[mode], "key": key, "created_at": utc_now_iso(),
            "video": info, "grid_hz": float(params["grid_hz"]),
            "gt_segments": None if segs is None else [[round(s, 4), round(e, 4), int(c)] for s, e, c in segs],
            "grid": {"t": [round(float(x), 4) for x in t_grid], "gt": None if gt is None else _nan_to_none(gt)},
            "_t": t_grid, "_gt": gt,
        }

    @staticmethod
    def _finish(result: dict[str, Any]) -> dict[str, Any]:
        result.pop("_t", None)
        result.pop("_gt", None)
        return result

    def _lidar_result(self, run_id, run, params, lid, key) -> dict[str, Any]:
        spec = self.lag_spec(run_id, run, params)
        yolo = self.load_yolo(run_id, run, params) if spec["source"] == "auto" else None
        lag = self.lag(run_id, run, params, lid, yolo, spec)
        res = self._base_result(run, "lidar", key, params)
        placed = place_lidar([{"t": r["t"], "count": r["smooth"], "raw": r["raw"], "tracked": r["tracked"]}
                              for r in lid["frames"]], res["_t"], lag["lag_s"])
        valid = placed["valid"]
        lag["window"] = [float(res["_t"][valid][0]), float(res["_t"][valid][-1])] if valid.any() else None
        lag["n_window"] = int(valid.sum())
        res["grid"].update(lidar=_nan_to_none(placed["count"]), lidar_raw=_nan_to_none(placed["raw"]),
                           lidar_tracked=_nan_to_none(placed["tracked"]), valid=[bool(v) for v in valid])
        res["metrics"] = {}
        if res["_gt"] is not None and valid.any():
            res["metrics"]["LiDAR"] = _metrics(placed["count"][valid], res["_gt"][valid], "LiDAR coverage")
        res.update(lidar_key=lid["key"], lag=lag, lidar_summary=lid["summary"],
                   latency={"lidar_ms": lid["summary"]["latency_ms_mean"]},
                   params={k: params[k] for k in ("lidar_offset_s",)} | {"lidar": lid["summary"]["params"]})
        return self._finish(res)

    def _camera_result(self, run_id, run, params, yolo, key) -> dict[str, Any]:
        res = self._base_result(run, "camera", key, params)
        conf = float(params["yolo_conf"])
        yolo_f = filter_records(yolo["records"], conf)
        yg = resample_counts(yolo_f, res["_t"])
        res["grid"]["yolo"] = _nan_to_none(yg)
        res["metrics"] = {}
        if res["_gt"] is not None:
            res["metrics"]["YOLO"] = _metrics(yg, res["_gt"], "whole video")
        res.update(yolo_key=yolo["key"], conf=conf, yolo_summary=yolo["summary"],
                   latency={"yolo_ms": yolo["summary"]["latency_ms_mean"]})
        return self._finish(res)

    def _fusion_result(self, run_id, run, params, lid, yolo, lag, key) -> dict[str, Any]:
        res = self._base_result(run, "fusion", key, params)
        t_grid, gt = res["_t"], res["_gt"]
        conf = float(params["yolo_conf"])
        yolo_f = filter_records(yolo["records"], conf)
        yg = resample_counts(yolo_f, t_grid)
        cg = resample_counts([{"t": r["t"], "count": r["conf_mean"]} for r in yolo_f], t_grid)
        placed = place_lidar([{"t": r["t"], "count": r["smooth"], "raw": r["raw"], "tracked": r["tracked"]}
                              for r in lid["frames"]], t_grid, lag["lag_s"])
        valid = placed["valid"]
        idx = np.where(valid)[0]
        k = int(params["cv_folds"])
        if len(idx) < 2 * k:
            raise AppError(f"Only {len(idx)} grid points where both sensors overlap: too few for {k}-fold CV. "
                           "Check the LiDAR offset.", code="no_overlap", status=409)
        t0 = time.time()
        ev = evaluate(placed["count"][idx], yg[idx], cg[idx], gt[idx], k)
        fit_s = time.time() - t0
        fused = np.full(len(t_grid), np.nan)
        fused[idx] = ev["oof"][FUSION_METHOD]
        lag["window"] = [float(t_grid[idx[0]]), float(t_grid[idx[-1]])]
        lag["n_window"] = int(len(idx))
        y = gt[idx]
        res["grid"].update(lidar=_nan_to_none(placed["count"]), yolo=_nan_to_none(yg), conf=_nan_to_none(cg, 4),
                           fused=_nan_to_none(fused, 4), valid=[bool(v) for v in valid])
        res["metrics"] = {
            "Fusion (Stack-GBT)": _metrics(ev["oof"][FUSION_METHOD], y, "overlap"),
            "LiDAR": _metrics(placed["count"][idx], y, "overlap"),
            "YOLO": _metrics(yg[idx], y, "overlap"),
        }
        gbt = next(r for r in ev["table"] if r["method"] == FUSION_METHOD)
        res["cv"] = {"method": FUSION_METHOD, "folds": k, "n": int(len(idx)),
                     "stack_gbt_mae": round(gbt["mae"], 6), "stack_gbt_mae_std": round(gbt["mae_std"], 6),
                     "table": [{**r, "mae": round(r["mae"], 6), "mae_std": round(r["mae_std"], 6),
                                "rmse": round(r["rmse"], 6)} for r in ev["table"]],
                     "auto": ev["auto"], "trivial": len(set(y.tolist())) == 1,
                     "oof_all": {m: _nan_to_none(self._full(ev["oof"][m], idx, len(t_grid)), 4)
                                 for m in FUSION_METHODS}}
        res.update(lidar_key=lid["key"], yolo_key=yolo["key"], conf=conf, lag=lag,
                   lidar_summary=lid["summary"], yolo_summary=yolo["summary"],
                   latency={"lidar_ms": lid["summary"]["latency_ms_mean"],
                            "yolo_ms": yolo["summary"]["latency_ms_mean"],
                            "fusion_fit_s": round(fit_s, 3)})
        return self._finish(res)

    @staticmethod
    def _full(values: np.ndarray, idx: np.ndarray, n: int) -> np.ndarray:
        a = np.full(n, np.nan)
        a[idx] = values
        return a

    # ================================================================== Analyze (everything)
    def process(self, run_id: str, job: Job) -> dict[str, Any]:
        """All three modes with the run's parameters + the run summary of the run page."""
        run = self.store.get(run_id)
        user = run.get("params") or {}
        params = full_params(user)
        timings: dict[str, float] = {}

        def timed(k: str, fn):
            job.check_cancelled()
            t0 = time.time()
            try:
                out = fn()
            except (AppError, Cancelled):
                raise
            except Exception as e:
                log.exception("Step %s failed for run %s", k, run_id)
                raise AppError(f"{STEP_LABELS[k]} failed: {type(e).__name__}: {e}", code="step_failed") from e
            timings[k] = round(time.time() - t0, 2)
            return out

        ex = timed("extract", lambda: self.extract(run_id, run, job))
        lid = timed("lidar", lambda: self.lidar(run_id, run, params, job, ex))
        yolo = timed("yolo", lambda: self.yolo(run_id, run, params, job))
        timed("transcode_camera", lambda: self.transcode(run_id, run, "camera_video", job, "transcode_camera"))
        media = {}
        if "lidar_screen" in run["files"]:
            media["lidar_screen"] = timed("transcode", lambda: self.transcode(run_id, run, "lidar_screen", job,
                                                                              "transcode"))
        job.start_step("align", "Cross-correlating the YOLO and LiDAR counts")
        lag = timed("align", lambda: self.lag(run_id, run, params, lid, yolo,
                                              self.lag_spec(run_id, run, params, yolo_will_exist=True)))
        job.finish_step("align", self._lag_message(lag))

        # the three mode results (cached for the Live view)
        lidar_res = self._lidar_result(run_id, run, params, lid, self.mode_key(run_id, run, "lidar", params))
        _write_json(self._mode_path(run_id, "lidar", lidar_res["key"]), lidar_res)
        cam_res = self._camera_result(run_id, run, params, yolo, self.mode_key(run_id, run, "camera", params))
        _write_json(self._mode_path(run_id, "camera", cam_res["key"]), cam_res)
        job.start_step("fusion", "Stack-GBT, blocked 5-fold CV, out-of-fold predictions")
        fus_res = None
        if run.get("ground_truth"):
            fus_res = timed("fusion", lambda: self._fusion_result(
                run_id, run, params, lid, yolo, dict(lag), self.mode_key(run_id, run, "fusion", params)))
            _write_json(self._mode_path(run_id, "fusion", fus_res["key"]), fus_res)
            job.finish_step("fusion", f"Stack-GBT blocked-CV MAE {fus_res['cv']['stack_gbt_mae']:.3f}")
        else:
            job.finish_step("fusion", "No ground truth: Fusion is not available", state="skipped")
        return self._summary(run, params, lid, yolo, lag, lidar_res, cam_res, fus_res, media, timings)

    def _summary(self, run, params, lid, yolo, lag, lidar_res, cam_res, fus_res, media, timings) -> dict[str, Any]:
        info = self._video_info(run)
        window = lidar_res["lag"].get("window")
        alignment = {
            "T": round(info["T"], 3), "grid_hz": float(params["grid_hz"]), "n_grid": len(lidar_res["grid"]["t"]),
            "lag_s": round(lag["lag_s"], 3), "auto_lag_s": lag.get("auto_lag_s"), "manual": lag["source"] == "manual",
            "r": lag.get("r"), "at_edge": lag.get("at_edge", False), "max_lag_s": float(params["max_lag_s"]),
            "note": lag.get("note"),
            "lidar_duration_s": lid["summary"]["duration_s"],
            "lidar_video_start_s": round(0.0 - lag["lag_s"], 3),
            "lidar_video_end_s": round(lid["summary"]["duration_s"] - lag["lag_s"], 3),
            "window": window, "n_window": lidar_res["lag"].get("n_window", 0), "yolo_conf": float(params["yolo_conf"]),
            "curve": lag.get("curve"),
        }
        if fus_res is None:
            fusion = {"has_gt": False, "n": alignment["n_window"], "folds": int(params["cv_folds"]),
                      "methods": [], "auto": None, "table": [],
                      "note": "No ground truth: Fusion and the metrics are not available."}
            metrics = []
        else:
            cv = fus_res["cv"]
            fusion = {"has_gt": True, "n": cv["n"], "folds": cv["folds"], "methods": [*FUSION_METHODS, "Auto"],
                      "auto": cv["auto"], "table": cv["table"], "learned": LEARNED_METHODS, "trivial": cv["trivial"],
                      "note": ("The ground truth is constant over the evaluation window, so learned fusion is "
                               "trivial here.") if cv["trivial"] else None}
            metrics = [{"method": k, **v} for k, v in fus_res["metrics"].items()]
            if "YOLO" in cam_res["metrics"]:
                metrics.append({"method": "YOLO (whole video)", **cam_res["metrics"]["YOLO"]})
        return {
            "pipeline_version": PIPELINE_VERSION, "params": run.get("params") or {},
            "lidar": lid["summary"], "yolo": yolo["summary"], "alignment": alignment, "fusion": fusion,
            "metrics": metrics, "timings": timings, "media": media,
            "modes": {m: r["key"] for m, r in (("lidar", lidar_res), ("camera", cam_res), ("fusion", fus_res)) if r},
        }

    # ================================================================== export
    def export_video(self, run_id: str, mode: str, user_params: dict[str, Any] | None, roi: bool,
                     job: Job) -> dict[str, Any]:
        run = self.store.get(run_id)
        params = full_params(user_params)
        key = self.mode_key(run_id, run, mode, params)
        path = self._mode_path(run_id, mode, key)
        if not path.is_file():
            raise AppError("Run this mode with the current parameters before exporting.", code="not_computed",
                           status=409)
        result = _read_json(path)
        info = self._video_info(run)
        exe, _ = find_ffmpeg()
        if not exe:
            raise AppError("ffmpeg is not available.", code="no_ffmpeg")
        conf = float(params["yolo_conf"])

        yolo_dets = None
        if mode in ("camera", "fusion"):
            recs = self.load_yolo(run_id, run, params)["records"]
            yolo_dets = [[d for d in r["detections"] if d["conf"] > conf] for r in recs]
        lidar = None
        if mode in ("lidar", "fusion"):
            lid = self.load_lidar(run_id, result["lidar_key"])
            d = self._cache(run_id) / "lidar" / result["lidar_key"]
            raw = (d / "points.bin").read_bytes()
            n = int(np.frombuffer(raw[:4], "<u4")[0])
            offsets = np.frombuffer(raw[4:4 + 4 * (n + 1)], "<u4").astype(np.int64)
            points = np.frombuffer(raw[4 + 4 * (n + 1):], "<i2").reshape(-1, 3)
            t_video = np.array([r["t"] for r in lid["frames"]]) - result["lag"]["lag_s"]
            lidar = {"t_video": t_video, "smooth": [r["smooth"] for r in lid["frames"]],
                     "clusters": [r["clusters"] for r in lid["frames"]], "points": points, "offsets": offsets,
                     "scene": _read_json(d / "scene.json"),
                     "period": 1.0 / (lid["summary"]["rate_hz"] or 7.8)}
        segs = [tuple(s) for s in result["gt_segments"]] if result.get("gt_segments") else None
        grid_t = np.array(result["grid"]["t"])
        gt_grid = result["grid"].get("gt")
        fused = result["grid"].get("fused") if mode == "fusion" else None
        hz = result["grid_hz"]

        def grid_at(arr, t):
            # sensors_fusion.ipynb cell 15: to_grid_idx(t) = clip(round(t * GRID_HZ), 0, len - 1)
            if arr is None:
                return None
            i = int(np.clip(round(t * hz), 0, len(grid_t) - 1))
            return arr[i]

        video = self.store.run_dir(run_id) / run["files"]["camera_video"]["local_name"]
        out_dir = self._cache(run_id) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{run_id}-{mode}-{stamp}.mp4"
        roi_px = np.array(self.calibration()["roi_px"]) if roi and mode in ("camera", "fusion") else None
        job.start_step("render", "Drawing the overlays", total=info["frames"], unit="frames")
        tmp = out_dir / (name + ".part.mp4")
        try:
            render_video(
                str(tmp), mode, ffmpeg=exe, fps=info["fps"], n_frames=info["frames"], video_path=str(video),
                yolo_dets=yolo_dets, roi_px=roi_px, lidar=lidar, gt_segments=segs,
                gt_at=lambda t: grid_at(gt_grid, t), fused_at=lambda t: grid_at(fused, t),
                on_progress=lambda i, n: job.update_step("render", done=i, total=n),
                should_stop=job.cancel_event.is_set)
        except RuntimeError as e:
            raise AppError(f"Rendering failed: {e}", code="render_failed") from e
        job.check_cancelled()
        os.replace(tmp, out_dir / name)
        size = (out_dir / name).stat().st_size
        job.finish_step("render", f"{name} ({size / 1e6:.1f} MB)")
        return {"file": name, "size": size, "mode": mode, "created_at": utc_now_iso()}
