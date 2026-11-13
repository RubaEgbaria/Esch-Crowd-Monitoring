"""Health check, ground-truth presets and default parameters."""
from __future__ import annotations

from fastapi import APIRouter

from pipeline.config import APP_DEFAULTS, DEFAULTS, MAX_LAG_S

from .. import __version__
from ..gt import presets_payload
from ..runs import ROLE_LABELS, utc_now_iso
from ..system import system_info

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "time": utc_now_iso()}


@router.get("/system")
def system() -> dict:
    """Compute device (CPU / GPU) and versions."""
    return system_info()


@router.get("/presets")
def presets() -> dict:
    return {
        "ground_truth": presets_payload(),
        "defaults": {**DEFAULTS, **APP_DEFAULTS, "max_lag_s": MAX_LAG_S},
        "roles": ROLE_LABELS,
    }
