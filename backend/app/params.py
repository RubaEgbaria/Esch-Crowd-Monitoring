"""Editable parameters of the Live view, with their "best" values.

The best values are the notebook defaults (sensors_fusion.ipynb CONFIG and
the function signatures of cell 9). eps = 0.10 was the best value of the eps
sweep in Qb2_people_counting.ipynb (cell 19): MAE 0.46 vs 0.63 / 0.84 / 1.18
for eps = 0.15 / 0.20 / 0.30.
"""
from __future__ import annotations

import math
from typing import Any

from pipeline.config import APP_DEFAULTS, DEFAULTS, MAX_LAG_S

from .errors import AppError

F, I, RNG, B, OFFSET = "float", "int", "range", "bool", "offset"

SCHEMA: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- LiDAR: foreground
    {"key": "bg_dist", "group": "LiDAR", "section": "Foreground", "label": "Background radius", "kind": F,
     "unit": "m", "min": 0.05, "max": 0.40, "step": 0.01,
     "help": "Background subtraction: a point is foreground if no point of the background cloud lies within "
             "this distance."},
    {"key": "min_h", "group": "LiDAR", "section": "Foreground", "label": "Min height above floor", "kind": F,
     "unit": "m", "min": 0.0, "max": 0.50, "step": 0.01,
     "help": "Foreground points lower than this above the fitted floor plane are dropped."},
    {"key": "zone_filter", "group": "LiDAR", "section": "Foreground", "label": "Occupancy zone filter", "kind": B,
     "help": "Keep only the points inside the Qb2 occupancy zone (perceptPipelineZones.json)."},
    # ---------------------------------------------------------------- LiDAR: clustering
    {"key": "dbscan_eps", "group": "LiDAR", "section": "Clustering", "label": "DBSCAN eps", "kind": F,
     "unit": "m", "min": 0.05, "max": 0.40, "step": 0.01,
     "help": "DBSCAN neighbourhood radius. 0.10 was the best in the eps sweep of Qb2_people_counting.ipynb "
             "(MAE 0.46; 0.15: 0.63, 0.20: 0.84, 0.30: 1.18)."},
    {"key": "dbscan_min_samples", "group": "LiDAR", "section": "Clustering", "label": "DBSCAN min samples",
     "kind": I, "min": 2, "max": 20, "step": 1,
     "help": "Minimum number of points in a DBSCAN neighbourhood (also the minimum cluster size)."},
    {"key": "single_person_span", "group": "LiDAR", "section": "Clustering", "label": "Single-person span",
     "kind": F, "unit": "m", "min": 0.30, "max": 1.20, "step": 0.05,
     "help": "A cluster wider than this is split with KMeans into round(span / this) people."},
    {"key": "max_split", "group": "LiDAR", "section": "Clustering", "label": "Max split", "kind": I,
     "min": 1, "max": 8, "step": 1,
     "help": "A cluster that would need more parts than this is treated as a wall / rail and dropped."},
    # ---------------------------------------------------------------- LiDAR: person filters
    {"key": "w_range", "group": "LiDAR", "section": "Person size", "label": "Width range", "kind": RNG,
     "unit": "m", "min": 0.05, "max": 2.0, "step": 0.01,
     "help": "Allowed cluster extent along u (floor axis)."},
    {"key": "d_range", "group": "LiDAR", "section": "Person size", "label": "Depth range", "kind": RNG,
     "unit": "m", "min": 0.05, "max": 2.0, "step": 0.01,
     "help": "Allowed cluster extent along v (floor axis)."},
    {"key": "top_range", "group": "LiDAR", "section": "Person size", "label": "Head height range", "kind": RNG,
     "unit": "m", "min": 0.3, "max": 3.0, "step": 0.05,
     "help": "Allowed height of the highest point of a cluster above the floor."},
    {"key": "min_height_ratio", "group": "LiDAR", "section": "Person size", "label": "Min height / footprint",
     "kind": F, "min": 0.2, "max": 1.0, "step": 0.05,
     "help": "Clusters flatter than this (height / max(width, depth)) are not people."},
    {"key": "min_pts_near", "group": "LiDAR", "section": "Person size", "label": "Min points (< 3 m)", "kind": I,
     "min": 1, "max": 80, "step": 1, "help": "Minimum points of a cluster closer than 3 m to the sensor footprint."},
    {"key": "min_pts_mid", "group": "LiDAR", "section": "Person size", "label": "Min points (3–5 m)", "kind": I,
     "min": 1, "max": 80, "step": 1, "help": "Minimum points of a cluster between 3 and 5 m."},
    {"key": "min_pts_far", "group": "LiDAR", "section": "Person size", "label": "Min points (> 5 m)", "kind": I,
     "min": 1, "max": 80, "step": 1, "help": "Minimum points of a cluster farther than 5 m."},
    # ---------------------------------------------------------------- LiDAR: tracking
    {"key": "track_max_dist", "group": "LiDAR", "section": "Tracking", "label": "Track max distance", "kind": F,
     "unit": "m", "min": 0.1, "max": 2.0, "step": 0.05,
     "help": "A detection further than this from a track is not matched to it."},
    {"key": "track_min_hits", "group": "LiDAR", "section": "Tracking", "label": "Track min hits", "kind": I,
     "min": 1, "max": 10, "step": 1, "help": "Frames a track must be seen before it is counted."},
    {"key": "track_max_miss", "group": "LiDAR", "section": "Tracking", "label": "Track max misses", "kind": I,
     "min": 0, "max": 15, "step": 1, "help": "Frames a track may be missed before it is deleted."},
    {"key": "smooth_window", "group": "LiDAR", "section": "Tracking", "label": "Smoothing window", "kind": I,
     "unit": "frames", "min": 1, "max": 20, "step": 1,
     "help": "Centred rolling median of the tracked count; 8 frames ≈ 1 s at 7.8 Hz."},
    # ---------------------------------------------------------------- YOLO
    {"key": "yolo_conf", "group": "YOLO", "section": "Detection", "label": "Confidence threshold", "kind": F,
     "min": 0.10, "max": 0.95, "step": 0.01, "instant": True,
     "help": "Boxes with a lower confidence are hidden and not counted. Applied instantly (YOLO is not rerun); "
             "the Fusion model is refit when you run it again."},
    # ---------------------------------------------------------------- Sync
    {"key": "lidar_offset_s", "group": "Sync", "section": "Alignment", "label": "LiDAR offset", "kind": OFFSET,
     "unit": "s", "min": -10.0, "max": 10.0, "step": 0.1,
     "help": "Auto: the lag is estimated by cross-correlating the YOLO and LiDAR counts (±5 s, as in the "
             "notebook). Manual: t_video = t_lidar − offset."},
]

BEST: dict[str, Any] = {**{k: DEFAULTS[k] for k in DEFAULTS if k in {s["key"] for s in SCHEMA}},
                        "lidar_offset_s": None}
BEST["yolo_conf"] = DEFAULTS["yolo_conf"]

# Not editable in the drawer, but part of the run parameters.
FIXED: dict[str, Any] = {
    "grid_hz": DEFAULTS["grid_hz"],
    "cv_folds": DEFAULTS["cv_folds"],
    "max_lag_s": MAX_LAG_S,
    "near_dist": DEFAULTS["near_dist"],
    "mid_dist": DEFAULTS["mid_dist"],
}


def schema_payload() -> list[dict[str, Any]]:
    out = []
    for s in SCHEMA:
        best = BEST[s["key"]]
        out.append({**s, "best": list(best) if isinstance(best, tuple) else best})
    return out


def _num(v: Any, s: dict[str, Any]) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise AppError(f"{s['label']}: expected a number.", code="bad_param", status=422)
    v = float(v)
    if v < s["min"] - 1e-9 or v > s["max"] + 1e-9:
        raise AppError(f"{s['label']}: {v:g} is outside {s['min']:g}–{s['max']:g}.", code="bad_param", status=422)
    return v


def normalize_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate user parameters; missing ones take the best (default) value."""
    raw = raw or {}
    out: dict[str, Any] = {}
    for s in SCHEMA:
        k = s["key"]
        if k not in raw:
            v = BEST[k]
            out[k] = list(v) if isinstance(v, tuple) else v
            continue
        v = raw[k]
        if s["kind"] == B:
            if not isinstance(v, bool):
                raise AppError(f"{s['label']}: expected true or false.", code="bad_param", status=422)
            out[k] = v
        elif s["kind"] == I:
            f = _num(v, s)
            if f != int(f):
                raise AppError(f"{s['label']}: expected a whole number.", code="bad_param", status=422)
            out[k] = int(f)
        elif s["kind"] == F:
            out[k] = round(_num(v, s), 6)
        elif s["kind"] == RNG:
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                raise AppError(f"{s['label']}: expected [min, max].", code="bad_param", status=422)
            lo, hi = _num(v[0], s), _num(v[1], s)
            if lo >= hi:
                raise AppError(f"{s['label']}: the minimum must be below the maximum.", code="bad_param", status=422)
            out[k] = [round(lo, 6), round(hi, 6)]
        elif s["kind"] == OFFSET:
            out[k] = None if v is None else round(_num(v, s), 3)
    return out


def full_params(user: dict[str, Any] | None) -> dict[str, Any]:
    """Validated user parameters + the fixed ones + YOLO settings, for the pipeline."""
    p = normalize_params(user)
    return {**DEFAULTS, **APP_DEFAULTS, **FIXED,
            "yolo_model": DEFAULTS["yolo_model"], "yolo_imgsz": DEFAULTS["yolo_imgsz"],
            **p, "w_range": tuple(p["w_range"]), "d_range": tuple(p["d_range"]),
            "top_range": tuple(p["top_range"])}
