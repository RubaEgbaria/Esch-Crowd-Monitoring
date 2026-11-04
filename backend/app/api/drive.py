"""Google Drive sign-in and folder resolution."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas import ResolveIn
from ..services import Services
from .deps import get_services

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/status")
def status(s: Services = Depends(get_services)) -> dict:
    return s.drive.status()


@router.post("/signin")
def signin(s: Services = Depends(get_services)) -> dict:
    return s.drive.start_signin()


@router.post("/signout")
def signout(s: Services = Depends(get_services)) -> dict:
    s.drive.signout()
    return s.drive.status()


@router.post("/resolve")
def resolve(body: ResolveIn, s: Services = Depends(get_services)) -> dict:
    return s.drive.resolve_folder(body.query)
