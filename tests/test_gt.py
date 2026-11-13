import pytest

from app.errors import AppError
from app.gt import check_segments, normalize_ground_truth, normalize_segments, normalize_token, presets_payload
from pipeline.sync import resolve_segments


@pytest.mark.parametrize("raw, expected", [
    (0, 0.0), (4.5, 4.5), ("5", 5.0), (" 5.25 ", 5.25),
    ("T", "T"), ("t", "T"), ("T-4", "T-4"), ("T-4.0", "T-4"), ("T - 3.5", "T-3.5"), ("T-.5", "T-0.5"),
])
def test_normalize_token_ok(raw, expected):
    assert normalize_token(raw) == expected


@pytest.mark.parametrize("raw", ["", "X-4", "T+4", "-1", -1, "abc", True, float("nan"), "inf"])
def test_normalize_token_bad(raw):
    with pytest.raises(ValueError):
        normalize_token(raw)


def test_baseline_preset_matches_notebook_on_43s_video():
    # sensors_fusion.ipynb: T = 454 / 10.52 = 43.16 s, segments (0,5,5),(5,T-4,6),(T-4,T,5)
    T = 454 / 10.52
    preset = next(p for p in presets_payload() if p["key"] == "baseline")
    segs = normalize_segments(preset["segments"])
    resolved = resolve_segments([(s["start"], s["end"], s["people"]) for s in segs], T)
    assert resolved == [(0.0, 5.0, 5), (5.0, T - 4, 6), (T - 4, T, 5)]
    rep = check_segments(segs, T)
    assert rep["ok"] and not rep["errors"] and not rep["warnings"]
    assert rep["constant"] is False


def test_all_presets_present():
    keys = {p["key"] for p in presets_payload()}
    assert keys == {"baseline", "with_items", "lights_off", "less_crowded"}
    less = next(p for p in presets_payload() if p["key"] == "less_crowded")
    assert check_segments(normalize_segments(less["segments"]), 30.0)["constant"] is True


def test_check_segments_reports_errors_and_gaps():
    rep = check_segments(normalize_segments([(0, 5, 5), (8, "T-50", 6)]), 43.0)
    assert not rep["ok"]
    assert any("must be after" in e for e in rep["errors"])

    rep = check_segments(normalize_segments([(0, 5, 5), (8, "T", 6)]), 43.0)
    assert rep["ok"]
    assert any("5.00–8.00 s" in w and "0 people" in w for w in rep["warnings"])

    rep = check_segments(normalize_segments([(0, 10, 5), (8, "T", 6)]), 43.0)
    assert any("overlap" in w for w in rep["warnings"])


def test_normalize_ground_truth_errors():
    with pytest.raises(AppError):
        normalize_ground_truth({"preset": None, "segments": []})
    with pytest.raises(AppError):
        normalize_ground_truth({"segments": [{"start": 0, "end": 5, "people": -1}]})
    with pytest.raises(AppError):
        normalize_ground_truth({"segments": [{"start": 0, "end": "Q", "people": 2}]})
    gt = normalize_ground_truth({"preset": "custom", "segments": [{"start": "0", "end": "T", "people": 3}]})
    assert gt == {"preset": None, "segments": [{"start": 0.0, "end": "T", "people": 3}]}
