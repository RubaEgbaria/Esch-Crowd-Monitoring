"""Compute device and tool versions (shown on the run page)."""
from __future__ import annotations

import os
import platform
import threading
from typing import Any

_lock = threading.Lock()
_info: dict[str, Any] | None = None


def system_info() -> dict[str, Any]:
    """CPU or GPU, library versions and the ffmpeg in use. Cached after the first call."""
    global _info
    with _lock:
        if _info is not None:
            return _info
        info: dict[str, Any] = {"cpu_count": os.cpu_count(), "platform": platform.platform(terse=True)}
        try:
            import torch
            import ultralytics

            from pipeline.camera import select_device

            device, label = select_device()
            info.update({
                "device": str(device), "device_label": label, "gpu": device != "cpu",
                "torch": torch.__version__, "ultralytics": ultralytics.__version__,
            })
        except Exception as e:  # torch/ultralytics missing or broken
            info.update({"device": "cpu", "device_label": "CPU", "gpu": False,
                         "error": f"YOLO is not available: {e}"})
        from .processing import find_ffmpeg

        exe, source = find_ffmpeg()
        info["ffmpeg"] = source if exe else None
        _info = info
        return info


def system_info_cached() -> dict[str, Any]:
    """The cached info if ready, without waiting for torch to import."""
    return _info or {}
