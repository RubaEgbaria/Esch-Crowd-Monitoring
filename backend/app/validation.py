"""Check a run's input files before processing.

Each check returns ``{"ok", "errors", "warnings", "info"}``. Errors block the
run; warnings are shown but do not block. Nothing is ever "fixed" silently:
if a file is missing or does not parse, the user gets a clear error.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import numpy as np

from .gt import check_segments
from .runs import ROLE_LABELS, utc_now_iso

# Same file names as find_recording() in sensors_fusion.ipynb (cell 4).
REQUIRED_JSON = (
    "perceptPipelineReferenceFrame.json",
    "perceptPipelineZones.json",
    "perceptPipelineDataSource.json",
)
FRAME_RE = re.compile(r"^frame_.*\.pb$")
BROWSER_CODECS = {"avc1", "h264", "x264", "hvc1", "hev1", "vp08", "vp09", "av01"}


def _report() -> dict[str, Any]:
    return {"ok": True, "errors": [], "warnings": [], "info": {}}


def _fail(rep: dict[str, Any], msg: str) -> dict[str, Any]:
    rep["errors"].append(msg)
    rep["ok"] = False
    return rep


def _is_unsafe(name: str) -> bool:
    n = name.replace("\\", "/")
    return n.startswith("/") or bool(re.match(r"^[A-Za-z]:", n)) or ".." in PurePosixPath(n).parts


# ---------------------------------------------------------------- LiDAR zip
def validate_lidar_zip(path: Path, on_frames: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Check the Qb2 zip. ``on_frames(done, total)`` reports frame parsing progress."""
    rep = _report()
    if not path.is_file():
        return _fail(rep, f"The LiDAR recording {path.name} is missing.")
    if not zipfile.is_zipfile(path):
        return _fail(rep, f"{path.name} is not a valid .zip archive.")

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        return _fail(rep, f"{path.name} cannot be opened: {e}")

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [i.filename for i in infos]
        unsafe = [n for n in names if _is_unsafe(n)]
        if unsafe:
            return _fail(rep, f"The zip contains unsafe paths (e.g. '{unsafe[0]}') and will not be extracted.")

        frames = sorted(n for n in names if FRAME_RE.match(PurePosixPath(n).name))
        rep["info"]["frames"] = len(frames)
        rep["info"]["uncompressed_mb"] = round(sum(i.file_size for i in infos) / 1e6, 1)
        if not frames:
            _fail(rep, "No frame_*.pb files found in the zip. Is this a Blickfeld Qb2 recording?")

        found = {req: [n for n in names if PurePosixPath(n).name == req] for req in REQUIRED_JSON}
        for req, hits in found.items():
            if not hits:
                _fail(rep, f"{req} is missing from the zip.")
        if not rep["ok"]:
            return rep

        def load_json(req: str) -> Any:
            try:
                return json.loads(zf.read(found[req][0]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise ValueError(f"{req} is not valid JSON: {e}") from None

        # --- background reference cloud (load_reference, cell 4)
        try:
            ref = load_json("perceptPipelineReferenceFrame.json")
            raw = base64.b64decode(ref["binary"]["cartesian"])
            if len(raw) % 12:
                raise ValueError("binary.cartesian is not a list of float32 (x, y, z) points")
            n_bg = len(raw) // 12
            if n_bg < 3:
                raise ValueError("the background cloud has fewer than 3 points")
            rep["info"]["background_points"] = n_bg
        except (KeyError, TypeError):
            _fail(rep, "perceptPipelineReferenceFrame.json has no binary.cartesian field.")
        except (ValueError, binascii.Error) as e:
            _fail(rep, f"perceptPipelineReferenceFrame.json: {e}")

        # --- occupancy zone (cell 8: zones[0]["shape"]["pose"/"box"])
        try:
            zones = load_json("perceptPipelineZones.json")
            if not isinstance(zones, list) or not zones:
                raise ValueError("no zone is defined")
            z = zones[0]
            pos = z["shape"]["pose"]["position"]
            dim = z["shape"]["box"]["dimensions"]
            rep["info"]["zone"] = {
                "name": z.get("name", "zone 1"),
                "center": [float(pos.get("x", 0)), float(pos.get("y", 0))],
                "size": [float(dim["x"]), float(dim["y"])],
            }
            rep["info"]["zones_count"] = len(zones)
            if len(zones) > 1:
                rep["warnings"].append(
                    f"{len(zones)} zones defined; the first one ('{rep['info']['zone']['name']}') is used, as in the notebook."
                )
        except (KeyError, TypeError):
            _fail(rep, "perceptPipelineZones.json: the first zone has no shape.pose.position / shape.box.dimensions.")
        except ValueError as e:
            _fail(rep, f"perceptPipelineZones.json: {e}")

        # --- mapFromLidar transform (cell 8)
        try:
            ds = load_json("perceptPipelineDataSource.json")
            mfl = ds["qb2Setup"]["lidars"][0]["mapFromLidar"]
            if not isinstance(mfl.get("rotation", {}), dict) or not isinstance(mfl.get("translation", {}), dict):
                raise ValueError("mapFromLidar.rotation / translation must be objects")
        except (KeyError, IndexError, TypeError):
            _fail(rep, "perceptPipelineDataSource.json has no qb2Setup.lidars[0].mapFromLidar.")
        except ValueError as e:
            _fail(rep, f"perceptPipelineDataSource.json: {e}")

        # --- frames: parse every frame (load_frame_pb, cell 4)
        try:
            from pipeline.qb2_io import parse_frame
            import blickfeld_qb2  # noqa: F401
        except ImportError:
            return _fail(rep, "The blickfeld_qb2 package is not installed in the backend environment.")

        parsed, failed = scan_frames(zf, frames, parse_frame, on_frames)
        n_empty = sum(1 for _, _, n in parsed if n == 0)
        errors, warnings = frame_rules(len(frames), failed, n_empty)
        for e in errors:
            _fail(rep, e)
        rep["warnings"].extend(warnings)

        counts = np.array([n for _, _, n in parsed], dtype=int)
        rep["info"].update({
            "frames_parsed": len(parsed),
            "frames_empty": n_empty,
            "frames_failed": len(failed),
        })
        if len(counts):
            rep["info"].update({
                "points_min": int(counts.min()),
                "points_median": int(np.median(counts)),
                "points_max": int(counts.max()),
                "points_total": int(counts.sum()),
            })
        if len(parsed) > 1:
            ts = np.array([t for _, t, _ in parsed], dtype=np.int64)
            duration = (ts[-1] - ts[0]) / 1e9
            rep["info"]["duration_s"] = round(float(duration), 3)
            backwards = int((np.diff(ts) <= 0).sum())
            if backwards:
                rep["warnings"].append(
                    f"Frame timestamps do not increase in {backwards} place(s): check the frame order."
                )
            if duration > 0:
                rep["info"]["rate_hz"] = round((len(parsed) - 1) / float(duration), 2)
    return rep


MAX_UNPARSEABLE_FRACTION = 0.10


def scan_frames(
    zf: zipfile.ZipFile,
    names: list[str],
    parse_frame: Callable[[bytes], tuple[int, int, Any]],
    on_frames: Callable[[int, int], None] | None = None,
) -> tuple[list[tuple[str, int, int]], list[tuple[str, str]]]:
    """Parse every frame. Returns ``(parsed, failed)``:
    parsed = [(name, timestamp_ns, n_points)], failed = [(name, reason)].
    A frame with 0 points is valid (empty frame); a frame without a
    timestamp cannot be placed in time and counts as failed.
    """
    parsed: list[tuple[str, int, int]] = []
    failed: list[tuple[str, str]] = []
    for i, name in enumerate(names):
        short = PurePosixPath(name).name
        try:
            _fid, ts, xyz = parse_frame(zf.read(name))
            if not ts:
                raise ValueError("no timestamp")
            parsed.append((name, int(ts), int(len(xyz))))
        except Exception as e:  # betterproto / numpy raise various error types
            failed.append((short, str(e) or type(e).__name__))
        if on_frames is not None and (i % 10 == 0 or i == len(names) - 1):
            on_frames(i + 1, len(names))
    return parsed, failed


def frame_rules(n_frames: int, failed: list[tuple[str, str]], n_empty: int) -> tuple[list[str], list[str]]:
    """Errors only for no frames or > 10 % unparseable frames; otherwise warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    n_failed = len(failed)
    examples = "; ".join(f"{name}: {reason}" for name, reason in failed[:3])
    if n_frames == 0:
        errors.append("No frame_*.pb files found in the zip. Is this a Blickfeld Qb2 recording?")
        return errors, warnings
    if n_failed > MAX_UNPARSEABLE_FRACTION * n_frames:
        errors.append(
            f"{n_failed} of {n_frames} frames ({100 * n_failed / n_frames:.0f}%) cannot be parsed, "
            f"more than the 10% allowed. E.g. {examples}"
        )
    elif n_failed:
        warnings.append(f"{n_failed} of {n_frames} frames cannot be parsed and will be skipped. E.g. {examples}")
    if n_empty:
        warnings.append(
            f"{n_empty} of {n_frames} frames are empty (0 points); they are kept as frames with 0 points, "
            "as in the notebook."
        )
    return errors, warnings


# ---------------------------------------------------------------- videos
def _fourcc(v: float) -> str:
    try:
        return int(v).to_bytes(4, "little").decode("ascii", errors="replace").strip("\x00 ").lower()
    except (OverflowError, ValueError):
        return ""


def validate_video(path: Path, label: str, *, browser_playback: bool = False) -> dict[str, Any]:
    import cv2

    rep = _report()
    if not path.is_file():
        return _fail(rep, f"The {label.lower()} {path.name} is missing.")
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return _fail(rep, f"{path.name} cannot be opened as a video.")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        codec = _fourcc(cap.get(cv2.CAP_PROP_FOURCC))
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        return _fail(rep, f"No frame could be decoded from {path.name}.")
    if fps <= 0 or n <= 0:
        return _fail(rep, f"{path.name} reports {fps:.2f} fps and {n} frames; cannot compute its duration.")
    rep["info"] = {
        "fps": round(fps, 3),
        "frames": n,
        "width": w or int(frame.shape[1]),
        "height": h or int(frame.shape[0]),
        # T = total_frames / fps, as in sensors_fusion.ipynb cell 5
        "duration_s": round(n / fps, 3),
        "codec": codec,
    }
    if browser_playback and codec and codec not in BROWSER_CODECS:
        rep["warnings"].append(
            f"{path.name} uses the '{codec}' codec, which browsers cannot play; "
            "processing makes an H.264 copy for the Sensor UI view."
        )
    return rep


# ---------------------------------------------------------------- whole run
def validate_ground_truth(run: dict[str, Any], camera_rep: dict[str, Any] | None) -> dict[str, Any] | None:
    gt = run.get("ground_truth")
    if not gt:
        return None
    if not camera_rep or not camera_rep["ok"]:
        rep = _report()
        rep["warnings"].append("The ground truth could not be checked because the camera video is not readable.")
        return rep
    return check_segments(gt["segments"], camera_rep["info"]["duration_s"])


def validate_run(
    run_dir: Path,
    run: dict[str, Any],
    on_progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    def progress(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    files = run["files"]
    out: dict[str, Any] = {"checked_at": utc_now_iso()}

    progress(0.05, "Checking the LiDAR recording")
    out["lidar_zip"] = validate_lidar_zip(
        run_dir / files["lidar_zip"]["local_name"],
        on_frames=lambda i, n: progress(0.05 + 0.55 * i / n, f"Parsing LiDAR frames ({i}/{n})"),
    )

    progress(0.6, "Checking the camera video")
    out["camera_video"] = validate_video(run_dir / files["camera_video"]["local_name"], ROLE_LABELS["camera_video"])

    if "lidar_screen" in files:
        progress(0.8, "Checking the sensor UI recording")
        out["lidar_screen"] = validate_video(
            run_dir / files["lidar_screen"]["local_name"], ROLE_LABELS["lidar_screen"], browser_playback=True
        )
    else:
        out["lidar_screen"] = None

    progress(0.95, "Checking the ground truth")
    out["ground_truth"] = validate_ground_truth(run, out["camera_video"])

    parts = [out["lidar_zip"], out["camera_video"], out["lidar_screen"], out["ground_truth"]]
    out["ok"] = all(p["ok"] for p in parts if p is not None)
    return out


def first_error(report: dict[str, Any]) -> str:
    for key in ("lidar_zip", "camera_video", "lidar_screen", "ground_truth"):
        part = report.get(key)
        if part and part["errors"]:
            label = ROLE_LABELS.get(key, "Ground truth")
            return f"{label}: {part['errors'][0]}"
    return "Validation failed"
