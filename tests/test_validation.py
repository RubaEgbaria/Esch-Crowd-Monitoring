"""Input validation: clear errors for broken inputs, real-data check when available."""
import json
import zipfile

import pytest

from app.validation import validate_lidar_zip, validate_video
from conftest import real_baseline_inputs


def _zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_not_a_zip(tmp_path):
    p = tmp_path / "rec.zip"
    p.write_bytes(b"this is not a zip archive")
    rep = validate_lidar_zip(p)
    assert not rep["ok"] and "not a valid .zip" in rep["errors"][0]


def test_missing_file(tmp_path):
    rep = validate_lidar_zip(tmp_path / "nope.zip")
    assert not rep["ok"] and "missing" in rep["errors"][0]


def test_zip_without_frames_or_metadata(tmp_path):
    p = _zip(tmp_path / "rec.zip", {"readme.txt": b"hello"})
    rep = validate_lidar_zip(p)
    assert not rep["ok"]
    joined = " | ".join(rep["errors"])
    assert "No frame_*.pb" in joined
    for name in ("perceptPipelineReferenceFrame.json", "perceptPipelineZones.json", "perceptPipelineDataSource.json"):
        assert f"{name} is missing" in joined


def test_zip_with_unsafe_paths(tmp_path):
    p = _zip(tmp_path / "rec.zip", {"../evil.txt": b"x"})
    rep = validate_lidar_zip(p)
    assert not rep["ok"] and "unsafe" in rep["errors"][0]


def test_zip_with_broken_metadata_and_frames(tmp_path):
    p = _zip(tmp_path / "rec.zip", {
        "rec/raw/frame_0001.pb": b"not a protobuf frame",
        "rec/perceptPipelineReferenceFrame.json": json.dumps({}).encode(),
        "rec/perceptPipelineZones.json": json.dumps([]).encode(),
        "rec/perceptPipelineDataSource.json": b"{not json",
    })
    rep = validate_lidar_zip(p)
    assert not rep["ok"]
    joined = " | ".join(rep["errors"])
    assert "binary.cartesian" in joined
    assert "no zone is defined" in joined
    assert "not valid JSON" in joined
    assert "frame_0001.pb" in joined


def test_unreadable_video(tmp_path):
    p = tmp_path / "raw-vid.mp4"
    p.write_bytes(b"\x00" * 1000)
    rep = validate_video(p, "Camera video")
    assert not rep["ok"]
    assert "cannot be opened" in rep["errors"][0] or "No frame could be decoded" in rep["errors"][0]


@pytest.mark.skipif(real_baseline_inputs() is None,
                    reason="put the baseline Qb2 .zip and raw-vid.mp4 in tests/fixtures/baseline/ to run")
def test_real_baseline_inputs():
    zip_path, video_path = real_baseline_inputs()
    lid = validate_lidar_zip(zip_path)
    assert lid["ok"], lid["errors"]
    # sensors_fusion.ipynb cell 8: 284 frames, background cloud 7680 pts, ~7.9 Hz
    assert lid["info"]["frames"] == 284
    assert lid["info"]["background_points"] == 7680
    assert 7.5 < lid["info"]["rate_hz"] < 8.2
    cam = validate_video(video_path, "Camera video")
    assert cam["ok"], cam["errors"]
    # sensors_fusion.ipynb cell 5: 10.520 fps | 454 frames | 43.16 s
    assert cam["info"]["frames"] == 454
    assert abs(cam["info"]["duration_s"] - 43.16) < 0.05
