"""Pick the LiDAR zip and the videos from a folder listing.

Rules (same as the notebooks):
  * LiDAR recording : the ``.zip`` (prefer the Qb2 name ``<ip>_<date>_<time>.zip``)
  * camera video    : the ``.mp4`` whose name does not contain "lidar"
                      (Complete_sensor_fusion / sensors_fusion); when several
                      match, prefer one with "raw" in its name (raw-vid.mp4 is
                      the cleaned video produced by vid_rectangle_cleaner)
  * sensor UI video : the ``.mp4`` whose name contains "lidar"
                      (e.g. lidar_top_view.mp4), optional
Everything else (json, .pt, subfolders such as outputs/) is ignored.
"""
from __future__ import annotations

import os
import re
from typing import Any

QB2_ZIP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.zip$", re.I)

# Any OpenCV-readable video works for the camera (frames are re-encoded to
# JPEG for streaming). The sensor UI recording is played by the browser, so
# it must be a browser-friendly container.
CAMERA_EXTS = (".mp4", ".m4v", ".mov", ".avi", ".mkv")
SCREEN_EXTS = (".mp4", ".m4v", ".webm", ".mov")


def ext(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def candidate_roles(name: str) -> list[str]:
    e = ext(name)
    roles = []
    if e == ".zip":
        roles.append("lidar_zip")
    if e in CAMERA_EXTS:
        roles.append("camera_video")
    if e in SCREEN_EXTS:
        roles.append("lidar_screen")
    return roles


def auto_select(files: list[dict[str, Any]]) -> dict[str, str | None]:
    """``files``: top-level files ``{"id", "name", "size"}``; returns ``{role: id | None}``."""
    zips = [f for f in files if ext(f["name"]) == ".zip"]
    zips.sort(key=lambda f: (not QB2_ZIP_RE.match(f["name"]), -(f.get("size") or 0), f["name"].lower()))

    mp4s = [f for f in files if ext(f["name"]) == ".mp4"]
    cams = [f for f in mp4s if "lidar" not in f["name"].lower()]
    cams.sort(key=lambda f: ("raw" not in f["name"].lower(), f["name"].lower()))
    screens = [f for f in mp4s if "lidar" in f["name"].lower()]
    screens.sort(key=lambda f: ("top_view" not in f["name"].lower(), f["name"].lower()))

    return {
        "lidar_zip": zips[0]["id"] if zips else None,
        "camera_video": cams[0]["id"] if cams else None,
        "lidar_screen": screens[0]["id"] if screens else None,
    }


def selection_notes(files: list[dict[str, Any]], selection: dict[str, str | None]) -> list[str]:
    notes = []
    n_zip = sum(ext(f["name"]) == ".zip" for f in files)
    n_cam = sum(ext(f["name"]) == ".mp4" and "lidar" not in f["name"].lower() for f in files)
    if selection.get("lidar_zip") is None:
        notes.append("No .zip found: the Qb2 LiDAR recording is required.")
    elif n_zip > 1:
        notes.append(f"{n_zip} .zip files found: check that the right LiDAR recording is selected.")
    if selection.get("camera_video") is None:
        notes.append("No camera .mp4 found (a .mp4 whose name does not contain 'lidar').")
    elif n_cam > 1:
        notes.append(f"{n_cam} camera videos found: check that the right one is selected.")
    return notes
