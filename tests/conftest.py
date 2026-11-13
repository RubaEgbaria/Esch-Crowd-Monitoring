from __future__ import annotations

from pathlib import Path

import pytest

from app.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        secrets_dir=tmp_path / "secrets",
        google_client_secrets=tmp_path / "secrets" / "google_client_secret.json",
        google_token_file=tmp_path / "secrets" / "google_token.json",
    )
    s.ensure_dirs()
    return s


def real_baseline_inputs() -> tuple[Path, Path] | None:
    """The real Qb2 zip + camera video, if the user put them in tests/fixtures/baseline/."""
    d = FIXTURES / "baseline"
    zips = sorted(d.glob("*.zip")) if d.is_dir() else []
    vids = sorted(p for p in d.glob("*.mp4") if "lidar" not in p.name.lower()) if d.is_dir() else []
    if zips and vids:
        return zips[0], vids[0]
    return None
