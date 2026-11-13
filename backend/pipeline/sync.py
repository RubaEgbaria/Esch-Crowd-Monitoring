"""Time alignment, ported from sensors_fusion.ipynb (cells 5 and 10).

Everything lives on the video timeline [0, T) sampled at ``grid_hz``. YOLO is
already on video time; the LiDAR is shifted by the cross-correlation lag.

One fix vs. the notebook: the notebook applied the lag with
``np.roll(lidar, -lag)``, which wraps the end of the signal around to the
start. Here the lag is applied to the LiDAR timestamps instead
(``t_lidar_video = t_lidar - lag_s``, same direction as the roll), and grid
points that the shifted LiDAR recording does not cover are marked missing
(NaN) instead of being filled with wrapped or repeated values. This matters
when the recordings have different lengths (baseline: LiDAR 36.3 s, video 43.2 s).
"""
from __future__ import annotations

from typing import Any

import numpy as np


# Source: sensors_fusion.ipynb, cell 5 (2.4 "Manual ground truth on the master grid")
def resolve_segments(segs, T):
    out = []
    for s, e, c in segs:
        s = T if s == "T" else (T - float(s.split("-")[1]) if isinstance(s, str) else float(s))
        e = T if e == "T" else (T - float(e.split("-")[1]) if isinstance(e, str) else float(e))
        out.append((s, e, c))
    return out


# Source: sensors_fusion.ipynb, cell 5 (2.4)
def sample_gt(t_grid, segs):
    y = np.zeros_like(t_grid, dtype=float)
    for s, e, c in segs:
        y[(t_grid >= s) & (t_grid < e)] = c
    return y


# Source: sensors_fusion.ipynb, cell 5 (2.5 "Resample camera & YOLO onto the grid")
def resample_counts(records, t_grid):
    ts = np.array([r["t"] for r in records])
    cs = np.array([r["count"] for r in records], dtype=float)
    idx = np.clip(np.searchsorted(ts, t_grid), 1, len(ts) - 1)
    return cs[idx]


# Source: sensors_fusion.ipynb, cell 10 (5.2 "Cross-correlation sanity check — sweep lag")
def best_lag(a, b, max_lag_samples):
    lags = np.arange(-max_lag_samples, max_lag_samples + 1)
    scores = []
    for l in lags:
        if l < 0:
            s = np.corrcoef(a[-l:], b[:l])[0, 1]
        elif l > 0:
            s = np.corrcoef(a[:-l], b[l:])[0, 1]
        else:
            s = np.corrcoef(a, b)[0, 1]
        scores.append(s)
    return lags[np.argmax(scores)], float(np.max(scores))


def lag_curve(a, b, max_lag_samples) -> tuple[np.ndarray, np.ndarray]:
    """The scores best_lag maximises, for display (NaN where a slice is constant)."""
    lags = np.arange(-max_lag_samples, max_lag_samples + 1)
    scores = []
    with np.errstate(invalid="ignore", divide="ignore"):
        for l in lags:
            if l < 0:
                s = np.corrcoef(a[-l:], b[:l])[0, 1]
            elif l > 0:
                s = np.corrcoef(a[:-l], b[l:])[0, 1]
            else:
                s = np.corrcoef(a, b)[0, 1]
            scores.append(s)
    return lags, np.array(scores, dtype=float)


def make_grid(T: float, grid_hz: float) -> np.ndarray:
    # Source: sensors_fusion.ipynb, cell 5: t_grid = np.arange(0, T, 1.0 / GRID_HZ)
    return np.arange(0, T, 1.0 / grid_hz)


def align(
    yolo_records: list[dict[str, Any]],
    lidar_records: list[dict[str, Any]],
    T: float,
    grid_hz: float,
    max_lag_s: float,
    manual_lag_s: float | None = None,
) -> dict[str, Any]:
    """Put YOLO and LiDAR counts on the video-time grid.

    ``yolo_records``: {"t", "count", "conf_mean"} per video frame.
    ``lidar_records``: {"t", "count" (smoothed), "raw", "tracked"} per LiDAR
    frame, ``t`` in seconds from the first LiDAR frame.
    The lag is found as in the notebook (best_lag between the YOLO grid and
    the unshifted LiDAR grid, ±max_lag_s) unless ``manual_lag_s`` is given.
    """
    t_grid = make_grid(T, grid_hz)
    yolo_grid = resample_counts(yolo_records, t_grid)
    conf_grid = resample_counts([{"t": r["t"], "count": r["conf_mean"]} for r in yolo_records], t_grid)
    est = estimate_lag(yolo_records, lidar_records, T, grid_hz, max_lag_s)
    lag_s = est["auto_lag_s"] if manual_lag_s is None else float(manual_lag_s)
    placed = place_lidar(lidar_records, t_grid, lag_s)
    return {
        "t_grid": t_grid,
        "yolo": yolo_grid,
        "conf": conf_grid,
        "lidar": placed["count"],
        "lidar_raw": placed["raw"],
        "lidar_tracked": placed["tracked"],
        "lidar_valid": placed["valid"],
        "t_lidar_video": placed["t_lidar_video"],
        "lag_s": lag_s,
        "manual": manual_lag_s is not None,
        **est,
    }


def estimate_lag(
    yolo_records: list[dict[str, Any]],
    lidar_records: list[dict[str, Any]],
    T: float,
    grid_hz: float,
    max_lag_s: float,
) -> dict[str, Any]:
    """The notebook's lag estimate (cell 10): best_lag between the YOLO grid and
    the unshifted LiDAR grid, ±max_lag_s. Handles constant signals (NaN scores)."""
    t_grid = make_grid(T, grid_hz)
    yolo_grid = resample_counts(yolo_records, t_grid)
    lidar_grid_unshifted = resample_counts(lidar_records, t_grid)

    max_lag = int(max_lag_s * grid_hz)
    lags, scores = lag_curve(yolo_grid, lidar_grid_unshifted, max_lag)
    if np.all(np.isnan(scores)):
        lag, r = 0, float("nan")       # a constant signal: no correlation to maximise
        note = "One of the signals is constant, so no lag could be estimated; lag set to 0."
    elif np.any(np.isnan(scores)):
        k = int(np.nanargmax(scores))
        lag, r = int(lags[k]), float(scores[k])
        note = None
    else:
        lag, r = best_lag(yolo_grid, lidar_grid_unshifted, max_lag)
        lag, note = int(lag), None
    return {
        "lag_samples": lag,
        "auto_lag_s": lag / grid_hz,
        "r": r,
        "at_edge": bool(abs(lag) == max_lag and max_lag > 0),
        "note": note,
        "curve": {"lag_s": (lags / grid_hz).tolist(),
                  "r": [None if np.isnan(s) else float(s) for s in scores]},
    }


def place_lidar(
    lidar_records: list[dict[str, Any]],
    t_grid: np.ndarray,
    lag_s: float,
    keys: tuple[str, ...] = ("count", "raw", "tracked"),
) -> dict[str, Any]:
    """Shift the LiDAR by the lag and resample it onto the video-time grid.

    Fix vs. the notebook's np.roll: the timestamps are shifted
    (t_video = t_lidar - lag_s) and grid points outside the shifted LiDAR
    recording are NaN instead of wrapped-around values.
    """
    t_lidar_video = np.array([r["t"] for r in lidar_records]) - lag_s
    valid = (t_grid >= t_lidar_video[0]) & (t_grid <= t_lidar_video[-1])
    out: dict[str, Any] = {"t_lidar_video": t_lidar_video, "valid": valid}
    for key in keys:
        g = resample_counts([{"t": float(t), "count": rec[key]} for rec, t in zip(lidar_records, t_lidar_video)],
                            t_grid)
        g[~valid] = np.nan
        out[key] = g
    return out
