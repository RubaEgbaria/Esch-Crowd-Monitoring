"""Google Drive sign-in and folder resolution."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..errors import AppError
from ..schemas import ResolveIn
from ..services import Services
from .deps import get_services

router = APIRouter(prefix="/api/drive", tags=["drive"])


DISABLED = ("Google Drive import is turned off on this server (its sign-in only works when the app runs "
            "on your own computer). Use Upload files instead.")


def _require_drive(s: Services) -> None:
    if not s.settings.drive_enabled:
        raise AppError(DISABLED, code="drive_disabled", status=409)


@router.get("/status")
def status(s: Services = Depends(get_services)) -> dict:
    if not s.settings.drive_enabled:
        return {"enabled": False, "client_configured": False, "client_message": DISABLED, "client_file": "",
                "signed_in": False, "account": None, "signin": {"state": "idle"}}
    return {"enabled": True, **s.drive.status()}


@router.post("/signin")
def signin(s: Services = Depends(get_services)) -> dict:
    _require_drive(s)
    return s.drive.start_signin()


@router.post("/signout")
def signout(s: Services = Depends(get_services)) -> dict:
    s.drive.signout()
    return s.drive.status()


@router.post("/resolve")
def resolve(body: ResolveIn, s: Services = Depends(get_services)) -> dict:
    _require_drive(s)
    return s.drive.resolve_folder(body.query)
