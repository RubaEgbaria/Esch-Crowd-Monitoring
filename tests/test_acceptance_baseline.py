"""Phase 2 acceptance: the app's pipeline reproduces sensors_fusion.ipynb on the baseline recording.

Needs the baseline inputs in tests/fixtures/baseline/ (the Qb2 .zip and raw-vid.mp4).
The whole job (LiDAR, YOLO, alignment, fusion) is run once into
tests/fixtures/baseline/_work/; YOLO is cached there, so later runs take seconds.

Two kinds of reference:
  * the values printed in the notebook's outputs (always available, embedded below);
  * the notebook's output files, when present in tests/fixtures/baseline/:
    lidar_counts.json, yolo_detections.json, ensemble_results.csv (per-frame checks).

An agreement report is written to tests/fixtures/baseline/_work/acceptance_report.json.

Note on the ground truth: the outputs saved in the notebook were produced with
the first baseline segment ending at 4.0 s, not 5.0 s as in the current CONFIG
cell: its df.describe() reports mean(manual_gt) = 5.814815 = 2512/432, which
only (0, 4.0, 5), (4.0, T-4, 6), (T-4, T, 5) gives. The comparisons with those
outputs therefore use NOTEBOOK_RUN_GT.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import mean_absolute_error

from app.gt import normalize_ground_truth
from app.jobs import Job
from app.services import Services
from app.settings import REPO_ROOT, Settings
from conftest import FIXTURES, real_baseline_inputs
from pipeline.camera import filter_records
from pipeline.fusion import blocked_cv_indices
from pipeline.metrics import counting_metrics
from pipeline.sync import best_lag, make_grid, resample_counts, resolve_segments, sample_gt

pytestmark = pytest.mark.skipif(
    real_baseline_inputs() is None,
    reason="put the baseline Qb2 .zip and raw-vid.mp4 in tests/fixtures/baseline/ to run",
)

BASELINE = FIXTURES / "baseline"
WORK = BASELINE / "_work"
REPORT: dict = {}

NOTEBOOK_RUN_GT = [(0, 4.0, 5), (4.0, "T-4", 6), ("T-4", "T", 5)]
CONFIG_GT = [(0, 5.0, 5), (5.0, "T-4", 6), ("T-4", "T", 5)]

# --- values printed in sensors_fusion.ipynb -----------------------------------------------
# cell 9: "LiDAR frame i/284 @ t=... → raw=.. tracked=.." every 20 frames
NB_LIDAR_LOG = {0: (5, 0), 20: (4, 4), 40: (6, 6), 60: (6, 6), 80: (6, 6), 100: (6, 6), 120: (5, 5),
                140: (6, 6), 160: (6, 6), 180: (6, 6), 200: (6, 4), 220: (5, 5), 240: (6, 6),
                260: (5, 5), 280: (4, 4)}
# Qb2_people_counting.ipynb cell 16: means of n_raw, n_tracked, n_smooth
NB_LIDAR_MEANS = (5.584507, 5.433099, 5.457746)
# cell 5: "YOLO frame i/454: n person(s)" every 50 frames
NB_YOLO_LOG = {0: 0, 50: 5, 100: 6, 150: 6, 200: 5, 250: 4, 300: 6, 350: 5, 400: 6, 450: 6}
# cell 10: df.describe() of the aligned grid (yolo, lidar after np.roll)
NB_DESCRIBE = {"yolo": (5.416667, 0.917729), "lidar": (5.231481, 0.846519)}
NB_LAG = (-5.00, 0.42)
# cell 12: blocked-CV results table (single-source rows)
NB_CV_MAE = {"LiDAR only": 0.583160, "YOLO only": 0.670730}
# cell 16: counting metrics
NB_METRICS = {
    "YOLO":  {"Precision": 97.48, "Recall": 90.80, "F1 Score": 94.02, "MAE": 0.67, "RMSE": 0.98,
              "Bias": -0.40, "Exact %": 45.83, "Within ±1 %": 88.43},
    "LiDAR": {"Precision": 100.00, "Recall": 89.97, "F1 Score": 94.72, "MAE": 0.58, "RMSE": 0.87,
              "Bias": -0.58, "Exact %": 50.00, "Within ±1 %": 91.67},
}


@pytest.fixture(scope="session")
def processed():
    """Process the baseline once (cached in _work/) and return the cached results."""
    zip_path, video_path = real_baseline_inputs()
    settings = Settings(
        data_dir=WORK / "data", cache_dir=WORK / "cache", secrets_dir=WORK / "secrets",
        google_client_secrets=WORK / "secrets" / "none.json", google_token_file=WORK / "secrets" / "none.json",
        models_dir=REPO_ROOT / "models",
    )
    svc = Services(settings)
    runs = [r for r in svc.store.list() if r["name"] == "acceptance-baseline"]
    if runs:
        run = runs[0]
    else:
        gt = normalize_ground_truth({"preset": "baseline", "segments": [list(s) for s in CONFIG_GT]})
        run = svc.store.create(
            name="acceptance-baseline", source={"kind": "upload"}, ground_truth=gt,
            files={"lidar_zip": {"name": zip_path.name, "size": zip_path.stat().st_size},
                   "camera_video": {"name": video_path.name, "size": video_path.stat().st_size}})
        for role, src in (("lidar_zip", zip_path), ("camera_video", video_path)):
            dst = svc.store.run_dir(run["id"]) / run["files"][role]["local_name"]
            try:
                os.link(src, dst)          # no second copy of 145 MB when possible
            except OSError:
                shutil.copy2(src, dst)
            svc.store.update_file(run["id"], role, status="ready", received=src.stat().st_size)
    run_id = run["id"]
    job = svc._new_job(svc.store.get(run_id), ingest=True)
    svc.store.attach_job(run_id, job)
    job.finish_step("upload", "fixture files", state="skipped")
    job.set_state("running")
    svc._work(run_id, job, ingest=True)          # synchronous; cached steps are reused
    cache = svc.store.cache_dir(run_id)
    out = {
        "svc": svc,
        "run_id": run_id,
        "run": svc.store.get(run_id),
        "lidar": json.loads((cache / "lidar" / "frames.json").read_text())["frames"],
        "yolo": json.loads((cache / "yolo" / "detections.json").read_text())["records"],
        "aligned": json.loads((cache / "aligned.json").read_text()),
    }
    yield out
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "acceptance_report.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print("\n=== Phase 2 acceptance report ===\n" + json.dumps(REPORT, indent=2))


def notebook_grid(p, gt_segments):
    """The notebook's aligned grid (cells 5 + 10), including its np.roll, for comparison only."""
    T = 454 / 10.520
    t = make_grid(T, 10)
    yolo_f = filter_records(p["yolo"], 0.25)
    yg = resample_counts(yolo_f, t)
    lg = resample_counts([{"t": r["t"], "count": r["smooth"]} for r in p["lidar"]], t)
    lag, r = best_lag(yg, lg, 50)
    lidar_rolled = np.roll(lg, -lag)
    gt = sample_gt(t, resolve_segments(gt_segments, T))
    return t, yg, lidar_rolled, gt, lag, r


def pct(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    return round(100.0 * float(np.mean(a == b)), 2)


# ---------------------------------------------------------------- LiDAR
def test_lidar_matches_notebook_log_and_means(processed):
    lid = processed["lidar"]
    assert len(lid) == 284
    for i, (raw, tracked) in NB_LIDAR_LOG.items():
        assert (lid[i]["raw"], lid[i]["tracked"]) == (raw, tracked), f"frame {i}"
    means = tuple(round(float(np.mean([r[k] for r in lid])), 6) for k in ("raw", "tracked", "smooth"))
    assert means == NB_LIDAR_MEANS
    REPORT["lidar_logged_frames_agreement_%"] = 100.0
    REPORT["lidar_means"] = {"app": means, "notebook": NB_LIDAR_MEANS}


def test_lidar_counts_match_lidar_counts_json(processed):
    ref_path = BASELINE / "lidar_counts.json"
    if not ref_path.is_file():
        pytest.skip("lidar_counts.json not in tests/fixtures/baseline/")
    ref = json.loads(ref_path.read_text())
    lid = processed["lidar"]
    assert len(ref) == len(lid)
    agree = {
        "raw": pct([r["raw"] for r in lid], [r["raw"] for r in ref]),
        "tracked": pct([r["tracked"] for r in lid], [r["tracked"] for r in ref]),
        "smoothed": pct([r["smooth"] for r in lid], [r["count"] for r in ref]),
    }
    REPORT["lidar_counts_json_agreement_%"] = agree
    assert agree == {"raw": 100.0, "tracked": 100.0, "smoothed": 100.0}


# ---------------------------------------------------------------- YOLO
def test_yolo_matches_notebook_log(processed):
    yf = filter_records(processed["yolo"], 0.25)
    assert len(yf) == 454
    got = {i: yf[i]["count"] for i in NB_YOLO_LOG}
    REPORT["yolo_logged_frames_agreement_%"] = pct(list(got.values()), list(NB_YOLO_LOG.values()))
    assert got == NB_YOLO_LOG


def test_yolo_counts_match_yolo_detections_json(processed):
    ref_path = BASELINE / "yolo_detections.json"
    if not ref_path.is_file():
        pytest.skip("yolo_detections.json not in tests/fixtures/baseline/")
    ref = json.loads(ref_path.read_text())
    yf = filter_records(processed["yolo"], 0.25)
    assert len(ref) == len(yf)
    agreement = pct([r["count"] for r in yf], [r["count"] for r in ref])
    REPORT["yolo_detections_json_agreement_%"] = agreement
    # Boxes whose confidence is within a hair of 0.25 can flip between library
    # versions / hardware; anything below 99 % would be a real porting error.
    assert agreement >= 99.0


# ---------------------------------------------------------------- grid, lag, MAE
def test_grid_lag_and_describe_match_notebook(processed):
    _, yg, lidar_rolled, _, lag, r = notebook_grid(processed, NOTEBOOK_RUN_GT)
    assert (lag / 10, round(r, 2)) == NB_LAG
    stats = {"yolo": (round(float(yg.mean()), 6), round(float(yg.std(ddof=1)), 6)),
             "lidar": (round(float(lidar_rolled.mean()), 6), round(float(lidar_rolled.std(ddof=1)), 6))}
    REPORT["grid_describe"] = {"app": stats, "notebook": NB_DESCRIBE}
    assert stats == NB_DESCRIBE


def test_single_source_cv_mae_close_to_notebook(processed):
    t, yg, lidar_rolled, gt, _, _ = notebook_grid(processed, NOTEBOOK_RUN_GT)
    folds = blocked_cv_indices(len(t), 5)
    cv = lambda a: float(np.mean([mean_absolute_error(gt[te], a[te]) for _, te in folds]))
    app = {"LiDAR only": round(cv(lidar_rolled), 6), "YOLO only": round(cv(yg), 6)}

    ref = dict(NB_CV_MAE)
    csv_path = BASELINE / "ensemble_results.csv"
    if csv_path.is_file():
        with open(csv_path, newline="") as f:
            ref = {row["Method"]: float(row["MAE"]) for row in csv.DictReader(f) if row["Method"] in NB_CV_MAE}
    REPORT["single_source_cv_mae (notebook alignment, notebook-run GT)"] = {"app": app, "notebook": ref}
    for k in NB_CV_MAE:
        assert abs(app[k] - ref[k]) < 0.005, (k, app[k], ref[k])


def test_counting_metrics_match_notebook(processed):
    _, yg, lidar_rolled, gt, _, _ = notebook_grid(processed, NOTEBOOK_RUN_GT)
    for name, pred in (("YOLO", yg), ("LiDAR", lidar_rolled)):
        m = {k: round(float(v), 2) for k, v in counting_metrics(pred, gt).items()}
        assert m == NB_METRICS[name], name
    REPORT["counting_metrics_agreement"] = "all 8 metrics equal for YOLO and LiDAR (cell 16)"


# ---------------------------------------------------------------- the app's own results (reported)
def test_report_app_alignment_and_fusion(processed):
    s = processed["run"]["results"]
    a = s["alignment"]
    assert a["lag_s"] == -5.0
    assert a["lidar_video_start_s"] == 5.0 and abs(a["lidar_video_end_s"] - 41.28) < 0.01
    assert a["n_window"] < a["n_grid"]            # the LiDAR does not cover the whole video
    al = processed["aligned"]
    assert all(v is None for v, ok in zip(al["lidar"], al["lidar_valid"]) if not ok)   # no wrapped values
    REPORT["app_alignment"] = {k: a[k] for k in ("T", "lag_s", "r", "at_edge", "lidar_duration_s",
                                                  "lidar_video_start_s", "lidar_video_end_s", "n_window", "n_grid")}
    f = s["fusion"]
    REPORT["app_fusion (2 sources, overlap window, preset GT)"] = {
        "auto": f["auto"], "n": f["n"],
        "table": {r["method"]: round(r["mae"], 4) for r in f["table"]},
    }
    assert f["auto"] in ("Mean", "WAvg (learned)", "Stack-LinReg", "Stack-GBT", "Conf-aware GBT")


# ---------------------------------------------------------------- Live view modes
def test_modes_are_cached_after_analyze_and_match_phase_2(processed):
    svc, run_id = processed["svc"], processed["run_id"]
    summary = processed["run"]["results"]
    res = {m: svc.processor.resolve(run_id, m, {}) for m in ("lidar", "camera", "fusion")}
    assert all(r["cached"] for r in res.values())
    lid, cam, fus = (res[m]["result"] for m in ("lidar", "camera", "fusion"))
    assert lid["lag"]["lag_s"] == -5.0 and lid["lag"]["source"] == "auto" and lid["lag"]["window"][0] == 5.0
    assert fus["metrics"]["Fusion (Stack-GBT)"]["n"] == 363
    assert fus["cv"]["stack_gbt_mae"] == pytest.approx(
        next(r["mae"] for r in summary["fusion"]["table"] if r["method"] == "Stack-GBT"), abs=1e-6)
    assert cam["metrics"]["YOLO"]["MAE"] == next(
        m["MAE"] for m in summary["metrics"] if m["method"] == "YOLO (whole video)")
    REPORT["live_modes"] = {m: res[m]["result"]["metrics"] for m in res}


def test_parameter_change_gives_a_new_key_and_is_cached_after_running(processed):
    svc, run_id = processed["svc"], processed["run_id"]
    base = svc.processor.resolve(run_id, "lidar", {})
    changed = svc.processor.resolve(run_id, "lidar", {"dbscan_eps": 0.15})
    assert changed["key"] != base["key"]
    if not changed["cached"]:
        job = Job(run_id, "mode:lidar", [("extract", "e"), ("lidar", "l"), ("lidar_results", "r")])
        job.set_state("running")
        svc.processor.run_mode(run_id, "lidar", {"dbscan_eps": 0.15}, job)
    again = svc.processor.resolve(run_id, "lidar", {"dbscan_eps": 0.15})
    assert again["cached"] and again["result"]["lidar_key"] != base["result"]["lidar_key"]
    # the YOLO confidence does not change the LiDAR-only key, it changes the Fusion key
    assert svc.processor.resolve(run_id, "lidar", {"yolo_conf": 0.5})["key"] == base["key"]
    assert svc.processor.resolve(run_id, "fusion", {"yolo_conf": 0.5})["key"] !=         svc.processor.resolve(run_id, "fusion", {})["key"]
    REPORT["lidar_eps_0.15_metrics"] = again["result"]["metrics"]


def test_camera_h264_copy_keeps_every_frame(processed):
    import cv2
    svc, run_id = processed["svc"], processed["run_id"]
    p = svc.processor.media_path(run_id, svc.store.get(run_id), "camera_video")
    cap = cv2.VideoCapture(str(p))
    n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), cap.get(cv2.CAP_PROP_FPS)
    codec = int(cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, "little").decode(errors="replace").lower()
    cap.release()
    assert n == 454 and abs(fps - 10.52) < 0.01 and codec in ("avc1", "h264")


def test_export_annotated_lidar_video(processed):
    import cv2
    svc, run_id = processed["svc"], processed["run_id"]
    job = Job(run_id, "export", [("render", "r")])
    job.set_state("running")
    out = svc.processor.export_video(run_id, "lidar", {}, True, job)
    p = svc.store.cache_dir(run_id) / "exports" / out["file"]
    cap = cv2.VideoCapture(str(p))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, frame = cap.read()
    cap.release()
    assert ok and n == 454 and frame.shape[:2] == (720, 720)
    REPORT["export"] = {"file": out["file"], "mb": round(out["size"] / 1e6, 2)}
