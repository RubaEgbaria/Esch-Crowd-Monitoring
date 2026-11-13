"""File auto-detection, Drive path parsing and file-name safety."""
import pytest

from app.drive import parse_query
from app.errors import AppError
from app.files_detect import auto_select, candidate_roles
from app.runs import safe_filename

# The real listing of the baseline folder (sensors_fusion.ipynb, cell 1).
BASELINE_FOLDER = [
    {"id": "a", "name": "192.168.137.36_2026-09-08_11-33-52.zip", "size": 132_100_000},
    {"id": "b", "name": "detection_counts.json", "size": 10_000},
    {"id": "c", "name": "lidar_top_view.mp4", "size": 21_000_000},
    {"id": "d", "name": "raw-vid.mp4", "size": 13_400_000},
    {"id": "e", "name": "yolo11m.pt", "size": 40_700_000},
]


def test_auto_select_baseline_folder():
    files = [f for f in BASELINE_FOLDER if candidate_roles(f["name"])]
    assert auto_select(files) == {"lidar_zip": "a", "camera_video": "d", "lidar_screen": "c"}


def test_auto_select_prefers_raw_video_and_qb2_zip():
    files = [
        {"id": "w", "name": "WhatsApp Video 2026-09-10 at 13.56.03.mp4", "size": 1},
        {"id": "r", "name": "raw-vid.mp4", "size": 1},
        {"id": "z1", "name": "backup.zip", "size": 999},
        {"id": "z2", "name": "192.168.137.36_2026-09-08_11-33-52.zip", "size": 5},
    ]
    sel = auto_select(files)
    assert sel["camera_video"] == "r" and sel["lidar_zip"] == "z2" and sel["lidar_screen"] is None


def test_candidate_roles():
    assert candidate_roles("x.zip") == ["lidar_zip"]
    assert candidate_roles("x.MP4") == ["camera_video", "lidar_screen"]
    assert candidate_roles("x.avi") == ["camera_video"]
    assert candidate_roles("x.json") == []


@pytest.mark.parametrize("text, expected", [
    ("My Drive/Crowd-Density-Monitoring/Code/baseline",
     {"kind": "path", "root": "my_drive", "parts": ["Crowd-Density-Monitoring", "Code", "baseline"]}),
    ("/content/drive/My Drive/Crowd-Density-Monitoring/Code/baseline",
     {"kind": "path", "root": "my_drive", "parts": ["Crowd-Density-Monitoring", "Code", "baseline"]}),
    ("/content/drive/MyDrive/Code/baseline/",
     {"kind": "path", "root": "my_drive", "parts": ["Code", "baseline"]}),
    ("Crowd-Density-Monitoring\\Code\\baseline",
     {"kind": "path", "root": "my_drive", "parts": ["Crowd-Density-Monitoring", "Code", "baseline"]}),
    ("Shared drives/AE3S/data", {"kind": "path", "root": "shared_drive", "parts": ["AE3S", "data"]}),
    ("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345?usp=sharing",
     {"kind": "id", "id": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"}),
    ("https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
     {"kind": "id", "id": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"}),
    ("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
     {"kind": "id", "id": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"}),
    ("1AbCdEfGhIjKlMnOpQrStUvWxYz012345", {"kind": "id", "id": "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"}),
])
def test_parse_query(text, expected):
    assert parse_query(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
                                  "https://drive.google.com/drive/my-drive"])
def test_parse_query_errors(text):
    with pytest.raises(AppError):
        parse_query(text)


@pytest.mark.parametrize("name, expected", [
    ("192.168.137.36_2026-09-08_11-33-52.zip", "192.168.137.36_2026-09-08_11-33-52.zip"),
    ("raw vid (1).mp4", "raw_vid_1.mp4"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\x\\raw-vid.mp4", "raw-vid.mp4"),
    ("vidéo.mp4", "vid_o.mp4"),
])
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected
