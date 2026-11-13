"""Qb2 LiDAR people counting, ported from sensors_fusion.ipynb (cells 8-9).

Same pipeline as Qb2_people_counting.ipynb: background subtraction with a
KD-tree, floor frame (u, v, h), occupancy-zone filter, DBSCAN + KMeans split,
nearest-neighbour tracking and a centred rolling median.

The notebook's globals (n_up, d_floor, u_ax, v_ax, bg_tree, zone transforms)
and CONFIG values are passed as arguments; the logic is unchanged.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation as R
from sklearn.cluster import DBSCAN, KMeans

from .config import DEFAULTS
from .qb2_io import load_frame_pb


# Source: sensors_fusion.ipynb, cell 8 (4.2 "Floor plane (RANSAC on the background)")
def fit_floor_plane(pts, iters=3000, thresh=0.05, seed=42):
    rng = np.random.default_rng(seed); best = (0, None, None)
    for _ in range(iters):
        p = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(p[1] - p[0], p[2] - p[0]); nl = np.linalg.norm(n)
        if nl < 1e-6:
            continue
        n /= nl; d = -n @ p[0]
        cnt = int((np.abs(pts @ n + d) < thresh).sum())
        if cnt > best[0]:
            best = (cnt, n, d)
    _, n, d = best
    inl = pts[np.abs(pts @ n + d) < thresh]; c = inl.mean(0)
    n = np.linalg.svd(inl - c)[2][2]; d = -n @ c
    if d < 0:
        n, d = -n, -d                          # sensor (origin) is above the floor
    a = np.array([1., 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1., 0])
    u = np.cross(n, a); u /= np.linalg.norm(u); v = np.cross(n, u)
    return n, d, u, v, best[0] / len(pts)


@dataclass
class Floor:
    """The notebook's globals n_up, d_floor, u_ax, v_ax (cell 8)."""
    n_up: np.ndarray
    d_floor: float
    u_ax: np.ndarray
    v_ax: np.ndarray
    floor_frac: float


# Source: sensors_fusion.ipynb, cell 8 (to_floor_frame); globals -> `floor`
def to_floor_frame(xyz, floor: Floor):
    return np.column_stack([xyz @ floor.u_ax, xyz @ floor.v_ax, xyz @ floor.n_up + floor.d_floor])


@dataclass
class Zone:
    """The notebook's globals of section 4.3 (cell 8)."""
    name: str
    map_from_lidar_R: R
    map_from_lidar_t: np.ndarray
    zone_R: R
    zc: dict
    zd: dict


# Source: sensors_fusion.ipynb, cell 8 (4.3 "Occupancy zone from the sensor config")
def load_zone(zones_path, ds_path) -> Zone:
    zones = json.load(open(zones_path))
    ds    = json.load(open(ds_path))
    mfl   = ds["qb2Setup"]["lidars"][0]["mapFromLidar"]
    q, t  = mfl["rotation"], mfl["translation"]
    map_from_lidar_R = R.from_quat([q.get("x", 0), q.get("y", 0), q.get("z", 0), q.get("w", 1)])
    map_from_lidar_t = np.array([t.get("x", 0), t.get("y", 0), t.get("z", 0)])

    zone = zones[0]
    zc  = zone["shape"]["pose"]["position"]; zd = zone["shape"]["box"]["dimensions"]
    zo  = zone["shape"]["pose"].get("orientation", {})
    zone_R = R.from_quat([zo.get("x", 0), zo.get("y", 0), zo.get("z", 0), zo.get("w", 1)])
    return Zone(zone.get("name", "zone 1"), map_from_lidar_R, map_from_lidar_t, zone_R, zc, zd)


# Source: sensors_fusion.ipynb, cell 8 (in_zone_xy); globals -> `zone`
def in_zone_xy(xyz, zone: Zone):
    m = zone.map_from_lidar_R.apply(xyz) + zone.map_from_lidar_t
    local = zone.zone_R.inv().apply(m - [zone.zc["x"], zone.zc["y"], zone.zc.get("z", 0)])
    return (np.abs(local[:, 0]) <= zone.zd["x"] / 2) & (np.abs(local[:, 1]) <= zone.zd["y"] / 2)


def zone_outline_floor(zone: Zone, floor: Floor) -> np.ndarray:
    """The 4 zone corners, zone -> map -> lidar -> floor frame, as (u, v). (Display only.)"""
    hx, hy = zone.zd["x"] / 2, zone.zd["y"] / 2
    local = np.array([[-hx, -hy, 0], [hx, -hy, 0], [hx, hy, 0], [-hx, hy, 0]], dtype=float)
    m = zone.zone_R.apply(local) + [zone.zc["x"], zone.zc["y"], zone.zc.get("z", 0)]
    lidar = zone.map_from_lidar_R.inv().apply(m - zone.map_from_lidar_t)
    return to_floor_frame(lidar, floor)[:, :2]


def zone_footprint_floor(zone: Zone, floor: Floor, h: float) -> np.ndarray:
    """Where the zone filter's volume crosses the height h above the floor, as (u, v). (Display only.)

    in_zone_xy ignores the zone-local z, so the kept volume is a prism along the
    zone's z axis. When that axis is not the floor normal (tilted map frame),
    the footprint depends on the height, so it is computed per height.
    """
    hx, hy = zone.zd["x"] / 2, zone.zd["y"] / 2
    centre = np.array([zone.zc["x"], zone.zc["y"], zone.zc.get("z", 0)])
    axis = zone.map_from_lidar_R.inv().apply(zone.zone_R.apply([0.0, 0.0, 1.0]))   # prism axis, lidar frame
    out = []
    for x, y in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
        p0 = zone.map_from_lidar_R.inv().apply(zone.zone_R.apply([x, y, 0.0]) + centre - zone.map_from_lidar_t)
        a, b = p0 @ floor.n_up + floor.d_floor, axis @ floor.n_up
        s = (h - a) / b if abs(b) > 1e-6 else 0.0
        p = p0 + s * axis
        out.append([p @ floor.u_ax, p @ floor.v_ax])
    return np.array(out)


def zone_tilt_deg(zone: Zone, floor: Floor) -> float:
    """Angle between the zone's z axis and the floor normal (0 = vertical prism)."""
    axis = zone.map_from_lidar_R.inv().apply(zone.zone_R.apply([0.0, 0.0, 1.0]))
    return float(np.degrees(np.arccos(min(1.0, abs(float(axis @ floor.n_up))))))


# Source: sensors_fusion.ipynb, cell 9 (filter_points); globals -> arguments.
# Additions: `zone_filter` (default on, as in the notebook) and an early return
# for empty frames (0 points), which the notebook never had to handle.
def filter_points(xyz, bg_tree, floor: Floor, zone: Zone,
                  bg_dist=DEFAULTS["bg_dist"], min_h=DEFAULTS["min_h"], zone_filter=True):
    if len(xyz) == 0:
        return np.empty((0, 3), dtype=float)
    f = to_floor_frame(xyz, floor)
    dist, _ = bg_tree.query(xyz, k=1, distance_upper_bound=bg_dist)
    fg = (~np.isfinite(dist)) & (f[:, 2] > min_h)
    if zone_filter:
        fg &= in_zone_xy(xyz, zone)
    return f[fg]


# Source: sensors_fusion.ipynb, cell 9 (split_oversized_cluster)
def split_oversized_cluster(pts, single_person_span=DEFAULTS["single_person_span"], max_split=DEFAULTS["max_split"]):
    w = np.ptp(pts[:, 0]); d = np.ptp(pts[:, 1])
    n_split = int(round(max(w, d) / single_person_span))
    if n_split <= 1:
        return [pts]
    if n_split > max_split:
        return []
    if len(pts) < n_split * 4:
        return [pts]
    km = KMeans(n_clusters=n_split, n_init=5, random_state=0).fit(pts[:, :2])
    return [pts[km.labels_ == k] for k in range(n_split)]


# Source: sensors_fusion.ipynb, cell 9 (cluster_pedestrians).
# The literals of `required = 25 if dist < 3 else 15 if dist < 5 else 8` and the
# split parameters are arguments with the same defaults.
def cluster_pedestrians(P, eps=DEFAULTS["dbscan_eps"], min_samples=DEFAULTS["dbscan_min_samples"],
                        w_range=DEFAULTS["w_range"], d_range=DEFAULTS["d_range"],
                        top_range=DEFAULTS["top_range"], min_height_ratio=DEFAULTS["min_height_ratio"],
                        single_person_span=DEFAULTS["single_person_span"], max_split=DEFAULTS["max_split"],
                        min_pts=(DEFAULTS["min_pts_near"], DEFAULTS["min_pts_mid"], DEFAULTS["min_pts_far"]),
                        dist_bins=(DEFAULTS["near_dist"], DEFAULTS["mid_dist"])):
    if len(P) < min_samples:
        return []
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(P)
    out = []
    for lbl in set(labels) - {-1}:
        for c in split_oversized_cluster(P[labels == lbl], single_person_span, max_split):
            if len(c) < min_samples:
                continue
            dist = np.linalg.norm(c[:, :2].mean(0))
            required = min_pts[0] if dist < dist_bins[0] else min_pts[1] if dist < dist_bins[1] else min_pts[2]
            if len(c) < required:
                continue
            w, d = np.ptp(c[:, 0]), np.ptp(c[:, 1]); top = c[:, 2].max(); h = top - c[:, 2].min()
            if max(w, d) == 0 or h / max(w, d) < min_height_ratio:
                continue
            if w_range[0] < w < w_range[1] and d_range[0] < d < d_range[1] and top_range[0] < top < top_range[1]:
                out.append({"centroid": c[:, :2].mean(0), "top": float(top),
                            "w": float(w), "d": float(d), "n": len(c)})
    return out


# Source: sensors_fusion.ipynb, cell 9 (SimpleTracker)
class SimpleTracker:
    def __init__(self, max_dist=DEFAULTS["track_max_dist"], min_hits=DEFAULTS["track_min_hits"],
                 max_miss=DEFAULTS["track_max_miss"]):
        self.tracks = {}; self.next_id = 0
        self.max_dist, self.min_hits, self.max_miss = max_dist, min_hits, max_miss
    def update(self, dets):
        cents = [d["centroid"] for d in dets]; used = set()
        for tid, t in list(self.tracks.items()):
            best, bj = self.max_dist, None
            for j, c in enumerate(cents):
                if j in used:
                    continue
                dd = np.linalg.norm(c - t["pos"])
                if dd < best:
                    best, bj = dd, j
            if bj is None:
                t["miss"] += 1
            else:
                t["pos"] = cents[bj]; t["hits"] += 1; t["miss"] = 0; used.add(bj)
            if t["miss"] > self.max_miss:
                del self.tracks[tid]
        for j, c in enumerate(cents):
            if j not in used:
                self.tracks[self.next_id] = {"pos": c, "hits": 1, "miss": 0}; self.next_id += 1
        return [(tid, t["pos"]) for tid, t in self.tracks.items()
                if t["hits"] >= self.min_hits and t["miss"] == 0]


def track_ids(tracker: SimpleTracker, dets: list[dict]) -> list[tuple[int | None, bool]]:
    """(track id, confirmed) of each detection after ``tracker.update(dets)``. Display only.

    A track updated or created in this frame has miss == 0 and its ``pos`` is
    the very centroid array of its detection, so the match is by identity.
    """
    by_obj = {id(d["centroid"]): j for j, d in enumerate(dets)}
    out: list[tuple[int | None, bool]] = [(None, False)] * len(dets)
    for tid, t in tracker.tracks.items():
        if t["miss"] == 0:
            j = by_obj.get(id(t["pos"]))
            if j is not None:
                out[j] = (tid, t["hits"] >= tracker.min_hits)
    return out


# Source: sensors_fusion.ipynb, cell 9 (the `smooth = ...` line)
def smooth_counts(tracked_counts, smooth_window=DEFAULTS["smooth_window"]):
    return (pd.Series(tracked_counts).rolling(smooth_window, center=True, min_periods=1)
            .median().astype(int).values)


# ----------------------------------------------------------------------------
# Scene set-up and the per-frame loop
# ----------------------------------------------------------------------------
@dataclass
class Scene:
    background: np.ndarray       # lidar frame (N, 3)
    background_f: np.ndarray     # floor frame (N, 3)
    bg_tree: cKDTree
    floor: Floor
    zone: Zone


def build_scene(background: np.ndarray, zones_path, ds_path) -> Scene:
    """Source: sensors_fusion.ipynb, cell 8 (4.2 + 4.3)."""
    n_up, d_floor, u_ax, v_ax, floor_frac = fit_floor_plane(background)
    floor = Floor(n_up, d_floor, u_ax, v_ax, floor_frac)
    return Scene(
        background=background,
        background_f=to_floor_frame(background, floor),
        bg_tree=cKDTree(background),
        floor=floor,
        zone=load_zone(zones_path, ds_path),
    )


def lidar_params(params: dict[str, Any]) -> dict[str, Any]:
    """The LiDAR subset of the app parameters, with tuples for ranges."""
    p = {**DEFAULTS, **(params or {})}
    return {
        "bg_dist": float(p["bg_dist"]), "min_h": float(p["min_h"]), "zone_filter": bool(p["zone_filter"]),
        "eps": float(p["dbscan_eps"]), "min_samples": int(p["dbscan_min_samples"]),
        "w_range": tuple(p["w_range"]), "d_range": tuple(p["d_range"]), "top_range": tuple(p["top_range"]),
        "min_height_ratio": float(p["min_height_ratio"]),
        "single_person_span": float(p["single_person_span"]), "max_split": int(p["max_split"]),
        "min_pts": (int(p["min_pts_near"]), int(p["min_pts_mid"]), int(p["min_pts_far"])),
        "dist_bins": (float(p["near_dist"]), float(p["mid_dist"])),
        "track_max_dist": float(p["track_max_dist"]), "track_min_hits": int(p["track_min_hits"]),
        "track_max_miss": int(p["track_max_miss"]), "smooth_window": int(p["smooth_window"]),
    }


def run_frames(
    frame_files: list[str],
    scene: Scene,
    lp: dict[str, Any],
    on_progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[dict[str, Any]]:
    """The loop of sensors_fusion.ipynb cell 9, one frame at a time (lazy).

    Yields per frame: frame_id, timestamp_ns, raw, tracked, fg points (u, v, h),
    clusters with their track id, latency_ms. Latency excludes disk I/O, like
    the notebook's efficiency cell (17).
    """
    tracker = SimpleTracker(lp["track_max_dist"], lp["track_min_hits"], lp["track_max_miss"])
    n = len(frame_files)
    for i, path in enumerate(frame_files):
        if should_stop is not None and should_stop():
            return
        fid, ts, xyz = load_frame_pb(path)
        t0 = time.perf_counter()
        P = filter_points(xyz, scene.bg_tree, scene.floor, scene.zone,
                          bg_dist=lp["bg_dist"], min_h=lp["min_h"], zone_filter=lp["zone_filter"])
        dets = cluster_pedestrians(P, eps=lp["eps"], min_samples=lp["min_samples"],
                                   w_range=lp["w_range"], d_range=lp["d_range"], top_range=lp["top_range"],
                                   min_height_ratio=lp["min_height_ratio"],
                                   single_person_span=lp["single_person_span"], max_split=lp["max_split"],
                                   min_pts=lp["min_pts"], dist_bins=lp["dist_bins"])
        tracked = tracker.update(dets)
        latency_ms = 1000 * (time.perf_counter() - t0)
        ids = track_ids(tracker, dets)
        yield {
            "index": i,
            "frame_id": int(fid),
            "timestamp_ns": int(ts),
            "raw": len(dets),
            "tracked": len(tracked),
            "points": P,
            "clusters": [
                {"u": float(d["centroid"][0]), "v": float(d["centroid"][1]), "w": d["w"], "d": d["d"],
                 "top": d["top"], "n": int(d["n"]), "track_id": tid, "confirmed": conf}
                for d, (tid, conf) in zip(dets, ids)
            ],
            "latency_ms": latency_ms,
        }
        if on_progress is not None:
            on_progress(i + 1, n)


def voxel_downsample(points: np.ndarray, voxel: float = 0.05, max_points: int = 15000) -> np.ndarray:
    """One point per occupied voxel (the first one), then a uniform cap. Display only."""
    if len(points) == 0:
        return points
    keys = np.floor(points / voxel).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    out = points[np.sort(first)]
    if len(out) > max_points:
        out = out[np.linspace(0, len(out) - 1, max_points).astype(int)]
    return out
