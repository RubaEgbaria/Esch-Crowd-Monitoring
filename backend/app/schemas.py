"""Request bodies of the HTTP API."""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

Role = Literal["lidar_zip", "camera_video", "lidar_screen"]
TimeToken = Union[float, str]


class GtSegmentIn(BaseModel):
    start: TimeToken
    end: TimeToken
    people: int


class GroundTruthIn(BaseModel):
    preset: str | None = None
    segments: list[GtSegmentIn]


class DriveFileIn(BaseModel):
    id: str = Field(min_length=5, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=300)
    size: int | None = Field(default=None, ge=0)


class DriveFolderIn(BaseModel):
    id: str
    name: str
    path: str = ""
    query: str = ""


class UploadFileIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    size: int = Field(gt=0)


class CreateRunIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source: Literal["drive", "upload"]
    ground_truth: GroundTruthIn | None = None
    drive_folder: DriveFolderIn | None = None
    drive_files: dict[Role, DriveFileIn] | None = None
    upload_files: dict[Role, UploadFileIn] | None = None


class PatchRunIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    ground_truth: GroundTruthIn | None = None
    clear_ground_truth: bool = False


class ResolveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
