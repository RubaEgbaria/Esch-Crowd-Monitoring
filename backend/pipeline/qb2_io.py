"""Qb2 recording I/O, ported from sensors_fusion.ipynb (cell 4)."""
from __future__ import annotations

import base64
import glob
import json
import os
import tempfile
import zipfile

import numpy as np


# Source: sensors_fusion.ipynb, cell 4 ("Qb2 recording loaders").
# Change: the zip is extracted into `extract_to` (cache/<run_id>/extracted)
# instead of a temporary folder, so it is extracted only once per run.
def find_recording(root, extract_to=None):
    if root.lower().endswith(".zip"):
        tmp = extract_to or tempfile.mkdtemp(prefix="qb2rec_")
        with zipfile.ZipFile(root) as z:
            z.extractall(tmp)
        root = tmp
    frames = sorted(glob.glob(os.path.join(root, "**", "frame_*.pb"), recursive=True))
    ref    = glob.glob(os.path.join(root, "**", "perceptPipelineReferenceFrame.json"), recursive=True)
    zones  = glob.glob(os.path.join(root, "**", "perceptPipelineZones.json"), recursive=True)
    ds     = glob.glob(os.path.join(root, "**", "perceptPipelineDataSource.json"), recursive=True)
    assert frames, "no frame_*.pb found"
    assert ref and zones and ds, "metadata json missing"
    return frames, ref[0], zones[0], ds[0]


def cartesian_to_xyz(cartesian) -> np.ndarray:
    """Convert ``frame.binary.cartesian`` to an ``(N, 3)`` float32 array.

    blickfeld_qb2 2.17 declares the field as bytes with
    ``numpy_dtype="(3,)<f4"`` and returns an ndarray of shape (N, 3). Other
    versions may return the raw little-endian bytes or a flat list of floats,
    so all three are accepted. A missing field (empty frame) gives 0 points.
    Raises ValueError when the data cannot be (x, y, z) float32 triples.
    """
    if cartesian is None:
        return np.empty((0, 3), dtype=np.float32)
    if isinstance(cartesian, (bytes, bytearray, memoryview)):
        buf = bytes(cartesian)
        if len(buf) % 12:
            raise ValueError(f"binary.cartesian has {len(buf)} bytes, not a multiple of 12 (x, y, z as float32)")
        return np.frombuffer(buf, dtype="<f4").reshape(-1, 3)
    arr = np.asarray(cartesian, dtype=np.float32)
    if arr.size % 3:
        raise ValueError(f"binary.cartesian has {arr.size} values, not a multiple of 3")
    return arr.reshape(-1, 3)


def parse_frame(data: bytes):
    """Parse the bytes of one ``frame_*.pb`` -> ``(id, timestamp_ns, xyz)``."""
    from blickfeld_qb2.core_processing.data import Frame

    fr = Frame().parse(data)
    binary = getattr(fr, "binary", None)
    xyz = cartesian_to_xyz(getattr(binary, "cartesian", None) if binary is not None else None)
    return fr.id, fr.timestamp, xyz


# Source: sensors_fusion.ipynb, cell 4, load_frame_pb.
# Same result as the notebook's np.asarray(fr.binary.cartesian, np.float32)
# .reshape(-1, 3); the conversion is done by cartesian_to_xyz so that raw-bytes
# versions of blickfeld_qb2 and empty frames (0 points) also work.
def load_frame_pb(path):
    with open(path, "rb") as f:
        return parse_frame(f.read())


# Source: sensors_fusion.ipynb, cell 4, load_reference.
def load_reference(path):
    r = json.load(open(path))
    return np.frombuffer(base64.b64decode(r["binary"]["cartesian"]), dtype=np.float32).reshape(-1, 3)
