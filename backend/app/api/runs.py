"""Runs: create (Drive or upload), list, inspect, rerun, cancel, delete."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..errors import AppError
from ..runs import ROLES
from ..schemas import CreateRunIn, PatchRunIn
from ..services import MAX_CHUNK_BYTES, Services
from .deps import get_services

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _role(role: str) -> str:
    if role not in ROLES:
        raise AppError(f"Unknown file role '{role}'.", code="bad_request", status=404)
    return role


@router.get("")
def list_runs(s: Services = Depends(get_services)) -> list[dict]:
    return s.store.list()


@router.post("", status_code=201)
def create_run(body: CreateRunIn, s: Services = Depends(get_services)) -> dict:
    return s.create_run(body)


@router.get("/{run_id}")
def get_run(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.store.get(run_id)


@router.patch("/{run_id}")
def patch_run(run_id: str, body: PatchRunIn, s: Services = Depends(get_services)) -> dict:
    return s.patch(run_id, body)


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, s: Services = Depends(get_services)) -> None:
    s.delete(run_id)


@router.post("/{run_id}/rerun")
def rerun(run_id: str, force: bool = False, s: Services = Depends(get_services)) -> dict:
    """Analyze / Retry / Rerun. Cached steps are reused unless force=true."""
    return s.rerun(run_id, force=force)


@router.post("/{run_id}/analyze")
def analyze(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.rerun(run_id)


@router.get("/{run_id}/results")
def results(run_id: str, s: Services = Depends(get_services)) -> dict:
    """Summary + the aligned 10 Hz grid + the fused predictions (cache files)."""
    run = s.store.get(run_id)
    if not run.get("results"):
        raise AppError("This run has not been processed yet.", code="not_processed", status=404)
    cache = s.store.cache_dir(run_id)
    try:
        aligned = json.loads((cache / "aligned.json").read_text(encoding="utf-8"))
        fusion = json.loads((cache / "fusion.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AppError("The cached results are missing; rerun the processing.", code="no_cache", status=404) from None
    return {"summary": run["results"], "aligned": aligned, "predictions": fusion["predictions"]}


@router.api_route("/{run_id}/media/lidar_screen", methods=["GET", "HEAD"])
def lidar_screen(run_id: str, s: Services = Depends(get_services)) -> FileResponse:
    """The sensor UI recording, as a browser-playable file (H.264 copy if transcoded)."""
    run = s.store.get(run_id)
    if "lidar_screen" not in run["files"]:
        raise AppError("This run has no sensor UI recording.", code="no_file", status=404)
    path = s.processor.media_path(run_id, run, "lidar_screen")
    if path is None or not path.is_file():
        raise AppError("The sensor UI recording is not prepared yet: process the run first.",
                       code="not_processed", status=404)
    return FileResponse(path, media_type="video/mp4")


@router.post("/{run_id}/cancel")
def cancel(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.cancel(run_id)


# ----------------------------------------------------------------- uploads
@router.put("/{run_id}/files/{role}/chunk")
async def upload_chunk(
    run_id: str,
    role: str,
    request: Request,
    offset: int = Query(ge=0),
    s: Services = Depends(get_services),
) -> dict:
    _role(role)
    length = request.headers.get("content-length")
    if length and int(length) > MAX_CHUNK_BYTES:
        raise AppError("Upload chunk too large.", code="chunk_too_large", status=413)
    data = await request.body()
    return await run_in_threadpool(s.receive_chunk, run_id, role, offset, data)


@router.post("/{run_id}/files/{role}/complete")
def upload_complete(run_id: str, role: str, s: Services = Depends(get_services)) -> dict:
    return s.complete_upload(run_id, _role(role))


@router.post("/{run_id}/start")
def start(run_id: str, s: Services = Depends(get_services)) -> dict:
    return s.start_after_upload(run_id)
