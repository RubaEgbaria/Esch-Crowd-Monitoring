"""Qb2 frame parsing: cartesian formats, frame rules, and the real baseline recording."""
import re
import zipfile

import numpy as np
import pytest

from app.validation import frame_rules, validate_lidar_zip
from conftest import real_baseline_inputs
from pipeline.qb2_io import cartesian_to_xyz, parse_frame

XYZ = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)


# ------------------------------------------------------------- cartesian formats
@pytest.mark.parametrize("value", [
    XYZ,                                   # blickfeld_qb2 2.17: ndarray (N, 3)
    XYZ.reshape(-1),                       # flat ndarray
    XYZ.astype("<f4").tobytes(),           # raw little-endian bytes
    bytearray(XYZ.astype("<f4").tobytes()),
    [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],        # flat list of floats
])
def test_cartesian_formats(value):
    out = cartesian_to_xyz(value)
    assert out.shape == (2, 3) and out.dtype == np.float32
    np.testing.assert_array_equal(out, XYZ)


def test_two_points_are_not_rejected():
    # The original bug: len() of an (N, 3) array is N, and N % 3 != 0 was rejected.
    assert cartesian_to_xyz(XYZ).shape == (2, 3)


@pytest.mark.parametrize("empty", [None, b"", np.empty((0, 3), np.float32), []])
def test_empty_frame_has_zero_points(empty):
    assert cartesian_to_xyz(empty).shape == (0, 3)


@pytest.mark.parametrize("bad", [b"\x00" * 13, [1.0, 2.0], np.zeros(4, np.float32)])
def test_malformed_cartesian_raises(bad):
    with pytest.raises(ValueError):
        cartesian_to_xyz(bad)


# ------------------------------------------------------------- frame rules
def test_frame_rules():
    assert frame_rules(0, [], 0)[0]                                   # no frames -> error
    assert frame_rules(284, [], 0) == ([], [])                        # all good
    err, warn = frame_rules(100, [("f.pb", "bad")] * 10, 0)           # exactly 10 % -> warning
    assert not err and "10 of 100 frames cannot be parsed" in warn[0]
    err, _ = frame_rules(100, [("f.pb", "bad")] * 11, 0)              # > 10 % -> error
    assert err and "11 of 100" in err[0]
    err, warn = frame_rules(284, [], 7)                               # empty frames -> warning only
    assert not err and "7 of 284 frames are empty" in warn[0]


# ------------------------------------------------------------- real baseline recording
needs_baseline = pytest.mark.skipif(
    real_baseline_inputs() is None,
    reason="put the baseline Qb2 .zip and raw-vid.mp4 in tests/fixtures/baseline/ to run",
)


@needs_baseline
def test_baseline_every_frame_parses_with_its_point_count():
    from blickfeld_qb2.core_processing.data import Frame

    zip_path, _ = real_baseline_inputs()
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(n for n in zf.namelist() if re.match(r"^frame_.*\.pb$", n.rsplit("/", 1)[-1]))
        assert len(names) == 284  # sensors_fusion.ipynb cell 8: "284 frames"
        counts = []
        for name in names:
            data = zf.read(name)
            _fid, ts, xyz = parse_frame(data)
            assert ts > 0
            assert xyz.dtype == np.float32 and xyz.ndim == 2 and xyz.shape[1] == 3
            # the frame's own point count (binary.length) must match
            assert xyz.shape[0] == Frame().parse(data).binary.length, name
            counts.append(xyz.shape[0])

    counts = np.array(counts)
    # Diagnosis of 2026-11-04 on this recording: no empty frames, 7315..7617 points.
    assert (counts > 0).all()
    assert counts[0] == 7598  # frame_1788867233369.pb, the frame that was wrongly rejected
    assert (counts.min(), int(np.median(counts)), counts.max()) == (7315, 7583, 7617)
    assert counts.sum() == 2_151_019


@needs_baseline
def test_baseline_zip_validates_cleanly():
    zip_path, _ = real_baseline_inputs()
    rep = validate_lidar_zip(zip_path)
    assert rep["ok"], rep["errors"]
    assert rep["warnings"] == []
    info = rep["info"]
    assert info["frames"] == info["frames_parsed"] == 284
    assert info["frames_empty"] == 0 and info["frames_failed"] == 0
    assert (info["points_min"], info["points_median"], info["points_max"]) == (7315, 7583, 7617)
    assert info["background_points"] == 7680
