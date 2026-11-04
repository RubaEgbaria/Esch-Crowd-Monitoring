"""Default parameters and ground-truth presets, copied from the notebooks.

Do not change a value here without changing it in the notebook first:
the notebooks are the source of truth.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Source: sensors_fusion.ipynb, cell 2 ("CONFIG — EDIT THIS BLOCK ONLY").
# Only the algorithm values are kept; file paths, camera-app and homography
# entries are not used by the app.
# ---------------------------------------------------------------------------
CONFIG_DEFAULTS: dict = {
    # YOLO
    "yolo_model": "yolo11m.pt",
    "yolo_conf": 0.25,
    "yolo_imgsz": 640,
    # LiDAR (same pipeline as Qb2_people_counting.ipynb)
    "bg_dist": 0.15,              # background subtraction radius [m]
    "min_h": 0.10,                # min height above floor [m]
    "dbscan_eps": 0.10,
    "dbscan_min_samples": 5,
    "w_range": (0.15, 1.05),
    "d_range": (0.15, 1.05),
    "top_range": (0.9, 2.3),
    "single_person_span": 0.65,
    "track_max_dist": 0.6,
    "track_min_hits": 3,
    "track_max_miss": 4,
    "smooth_window": 8,           # ~1 s at 7.8 Hz
    # Time grid & CV
    "grid_hz": 10,
    "cv_folds": 5,
}

# ---------------------------------------------------------------------------
# Defaults that live in function signatures rather than in CONFIG.
# Source: sensors_fusion.ipynb, cell 9 (split_oversized_cluster,
# cluster_pedestrians) and Qb2_people_counting.ipynb, cell 12.
# ---------------------------------------------------------------------------
SIGNATURE_DEFAULTS: dict = {
    "max_split": 4,                # split_oversized_cluster(max_split=4)
    "min_height_ratio": 0.5,       # cluster_pedestrians(min_height_ratio=0.5)
    # required = 25 if dist < 3 else 15 if dist < 5 else 8
    "min_pts_near": 25,
    "min_pts_mid": 15,
    "min_pts_far": 8,
    "near_dist": 3.0,
    "mid_dist": 5.0,
    # filter_points(): the zone filter is always on in the notebooks
    "zone_filter": True,
}

# Source: sensors_fusion.ipynb, cell 10: max_lag = int(5 * GRID_HZ)  (±5 s)
MAX_LAG_S = 5.0

# The LiDAR/YOLO lag is always estimated with YOLO counts at the notebook's
# confidence (CONFIG["yolo_conf"]), so moving the confidence slider in the app
# never moves the LiDAR in time.
ALIGN_CONF = 0.25

# ---------------------------------------------------------------------------
# Source: sensors_fusion.ipynb, cell 2 (CONFIG): ROI on the floor and the
# 4-point floor -> pixel homography ("measure these in the lab"). These are
# approximate: the app labels the ROI "approximate calibration".
# ---------------------------------------------------------------------------
CALIBRATION: dict = {
    "roi_floor_xy": [[-2.0, 1.0], [2.0, 1.0], [2.0, 6.0], [-2.0, 6.0]],
    "floor_calib_xy": [[-2.0, 1.0], [2.0, 1.0], [2.0, 6.0], [-2.0, 6.0]],
    "floor_calib_uv": [[320, 480], [960, 480], [1100, 100], [180, 100]],
}

# App-only values (not in the notebooks), from the web-app specification.
APP_DEFAULTS: dict = {
    # YOLO is run once at this low threshold and all boxes are stored, so the
    # confidence slider can filter later without re-running YOLO.
    "yolo_store_conf": 0.10,
}

DEFAULTS: dict = {**CONFIG_DEFAULTS, **SIGNATURE_DEFAULTS}


# ---------------------------------------------------------------------------
# Ground-truth presets: (start_s, end_s, people); "T" = video duration,
# "T-x" = x seconds before the end.
# ---------------------------------------------------------------------------
GT_PRESETS: dict = {
    # Source: sensors_fusion.ipynb, cell 2, CONFIG["manual_gt_segments"]
    "baseline": {
        "label": "Baseline",
        "description": "Standard video - crowded middle section",
        "source": "sensors_fusion.ipynb, cell 2 (CONFIG['manual_gt_segments'])",
        "segments": [
            (0, 5.0, 5),
            (5.0, "T-4", 6),
            ("T-4", "T", 5),
        ],
    },
    # Source: lab_experiment_pedestrian_camera.ipynb, cell 9, VIDEO_CONFIGS
    "with_items": {
        "label": "With items",
        "description": "People carrying items",
        "source": "lab_experiment_pedestrian_camera.ipynb, cell 9 (VIDEO_CONFIGS)",
        "segments": [
            (0, 5.0, 4),
            (5.0, "T-3.0", 6),
            ("T-3.0", "T", 5),
        ],
    },
    "lights_off": {
        "label": "Lights off",
        "description": "Low lighting conditions",
        "source": "lab_experiment_pedestrian_camera.ipynb, cell 9 (VIDEO_CONFIGS)",
        "segments": [
            (0, 6.0, 5),
            (6.0, "T-3.0", 6),
            ("T-3.0", "T", 5),
        ],
    },
    "less_crowded": {
        "label": "Less crowded",
        "description": "Consistently sparse",
        "source": "lab_experiment_pedestrian_camera.ipynb, cell 9 (VIDEO_CONFIGS)",
        "segments": [(0, "T", 5)],
    },
}
