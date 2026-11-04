"""YOLO11m person detection on the camera video, ported from sensors_fusion.ipynb (cell 5, 2.2).

YOLO is run once at a low confidence (0.10) and every person box is stored,
so the confidence threshold can be changed later without running YOLO again.
Filtering the stored boxes with ``conf > threshold`` gives the same boxes as
running YOLO at that threshold: Ultralytics keeps candidates with score
``> conf`` before NMS, and lower-scored boxes can never suppress higher ones.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from .config import DEFAULTS


def select_device() -> tuple[str | int, str]:
    """GPU if available, otherwise CPU. Returns (device for Ultralytics, label)."""
    import torch

    if torch.cuda.is_available():
        return 0, f"GPU ({torch.cuda.get_device_name(0)})"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps", "GPU (Apple MPS)"
    return "cpu", "CPU"


def ensure_model(path: Path) -> Path:
    """Download the official YOLO weights into ``path`` if they are missing."""
    if not path.is_file():
        from ultralytics.utils.downloads import attempt_download_asset

        path.parent.mkdir(parents=True, exist_ok=True)
        attempt_download_asset(str(path))
    if not path.is_file():
        raise FileNotFoundError(f"YOLO weights not found and could not be downloaded: {path}")
    return path


# Source: sensors_fusion.ipynb, cell 5 (2.2 "YOLO pedestrian detection (every frame, keep boxes)").
# Changes: CONFIG -> arguments; boxes are kept unrounded (full precision conf)
# so thresholds can be applied later; per-frame inference latency is recorded.
def run_yolo(
    video_path: Path,
    model_path: Path,
    conf: float = 0.10,
    imgsz: int = DEFAULTS["yolo_imgsz"],
    device: str | int = "cpu",
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    yolo_records = []
    frame_idx = 0
    try:
        while True:
            if should_stop is not None and should_stop():
                break
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)   # as in the notebook
            t0 = time.perf_counter()
            res = model(rgb, conf=conf, imgsz=imgsz, verbose=False, device=device)[0]
            latency_ms = 1000 * (time.perf_counter() - t0)
            dets = []
            for b in res.boxes:
                if res.names[int(b.cls)] != "person":
                    continue
                x1, y1, x2, y2 = b.xyxy[0].tolist()
                dets.append({"box": [x1, y1, x2, y2], "conf": float(b.conf)})
            yolo_records.append({
                "frame": frame_idx,
                "t": frame_idx / fps,
                "detections": dets,
                "latency_ms": latency_ms,
            })
            frame_idx += 1
            if on_progress is not None:
                on_progress(frame_idx, max(total_frames, frame_idx))
    finally:
        cap.release()
    return {"fps": fps, "frames": len(yolo_records), "records": yolo_records}


# Source: sensors_fusion.ipynb, cell 7 (3.1 "Build homography from 4 floor correspondences").
# CONFIG values -> arguments.
def roi_polygon_px(floor_calib_xy, floor_calib_uv, roi_floor_xy) -> np.ndarray:
    src = np.array(floor_calib_xy, dtype=np.float32)   # floor metres
    dst = np.array(floor_calib_uv, dtype=np.float32)   # pixels
    H, _ = cv2.findHomography(src, dst)

    def floor_xy_to_px(xy):
        pts = np.array(xy, dtype=np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, H).reshape(-1, 2)

    return floor_xy_to_px(roi_floor_xy)


def filter_records(yolo_records: list[dict], threshold: float = DEFAULTS["yolo_conf"]) -> list[dict]:
    """Per frame: the person boxes with conf > threshold, their count and mean conf.

    ``count`` is the notebook's YOLO count; ``conf_mean`` is the per-frame
    confidence of cell 12: mean box confidence, 0.0 when there is no box.
    """
    out = []
    for r in yolo_records:
        dets = [d for d in r["detections"] if d["conf"] > threshold]
        out.append({
            "frame": r["frame"],
            "t": r["t"],
            "count": len(dets),
            "conf_mean": float(np.mean([d["conf"] for d in dets])) if dets else 0.0,
            "detections": dets,
        })
    return out
