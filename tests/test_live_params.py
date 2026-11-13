"""Live-view parameters and the notebook's ROI homography (no sensor data needed)."""
import numpy as np
import pytest

from app.errors import AppError
from app.params import BEST, SCHEMA, full_params, normalize_params, schema_payload
from pipeline.camera import roi_polygon_px
from pipeline.config import CALIBRATION, DEFAULTS


def test_best_values_are_the_notebook_defaults():
    by_key = {s["key"]: s for s in schema_payload()}
    assert by_key["dbscan_eps"]["best"] == 0.10 and "eps sweep" in by_key["dbscan_eps"]["help"]
    for k in ("bg_dist", "min_h", "dbscan_min_samples", "single_person_span", "max_split", "min_height_ratio",
              "track_max_dist", "track_min_hits", "track_max_miss", "smooth_window", "yolo_conf",
              "min_pts_near", "min_pts_mid", "min_pts_far"):
        assert by_key[k]["best"] == DEFAULTS[k], k
    assert by_key["w_range"]["best"] == [0.15, 1.05] and by_key["top_range"]["best"] == [0.9, 2.3]
    assert by_key["lidar_offset_s"]["best"] is None
    for s in SCHEMA:   # every best value lies inside its slider range
        b = BEST[s["key"]]
        if s["kind"] in ("float", "int"):
            assert s["min"] <= b <= s["max"], s["key"]


def test_normalize_params_defaults_and_errors():
    p = normalize_params({})
    assert p["dbscan_eps"] == 0.10 and p["zone_filter"] is True and p["lidar_offset_s"] is None
    assert normalize_params({"dbscan_eps": 0.15, "w_range": [0.2, 0.9], "lidar_offset_s": -6.1})["lidar_offset_s"] == -6.1
    for bad in ({"dbscan_eps": 0.9}, {"dbscan_min_samples": 2.5}, {"w_range": [0.9, 0.2]},
                {"zone_filter": "yes"}, {"yolo_conf": "high"}):
        with pytest.raises(AppError):
            normalize_params(bad)
    fp = full_params({"top_range": [1.0, 2.0]})
    assert fp["top_range"] == (1.0, 2.0) and fp["yolo_store_conf"] == 0.10 and fp["grid_hz"] == 10


def test_roi_homography_port():
    # sensors_fusion cell 7: the ROI uses the same 4 floor points as the calibration,
    # so the homography maps it exactly onto floor_calib_uv.
    roi = roi_polygon_px(CALIBRATION["floor_calib_xy"], CALIBRATION["floor_calib_uv"], CALIBRATION["roi_floor_xy"])
    np.testing.assert_allclose(roi, np.array(CALIBRATION["floor_calib_uv"], float), atol=1e-3)
