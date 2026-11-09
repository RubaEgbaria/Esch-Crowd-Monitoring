"""Paths and environment settings for the local backend.

Everything lives inside the repository by default:
  data/runs/<run_id>/   input files of each run (+ run.json)
  cache/<run_id>/       processing results (Phase 2+)
  secrets/              Google OAuth client + token (never committed)

Each path can be overridden in a `.env` file at the repository root
(see `.env.example`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

# Allow the Flutter dev server (any port) on localhost to call the API.
DEFAULT_CORS_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    cache_dir: Path
    secrets_dir: Path
    google_client_secrets: Path
    google_token_file: Path
    cors_origin_regex: str = DEFAULT_CORS_REGEX
    models_dir: Path = REPO_ROOT / "models"
    # --- hosting (all optional; unset = local laptop behaviour) ---
    app_password: str | None = None      # shared password (HTTP Basic auth) for a public server
    web_dir: Path | None = None          # built Flutter web app served at "/" (one server for everything)
    drive_enabled: bool = True           # Google Drive import (its sign-in only works on a laptop)
    seed_dir: Path | None = None         # pre-processed runs copied into data/ and cache/ at start-up

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def ensure_dirs(self) -> None:
        for d in (self.runs_dir, self.cache_dir, self.secrets_dir):
            d.mkdir(parents=True, exist_ok=True)


def _resolve(value: str | None, default: Path) -> Path:
    p = Path(value) if value else default
    return p if p.is_absolute() else REPO_ROOT / p


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    secrets = _resolve(os.getenv("CROWD_SECRETS_DIR"), REPO_ROOT / "secrets")
    return Settings(
        data_dir=_resolve(os.getenv("CROWD_DATA_DIR"), REPO_ROOT / "data"),
        cache_dir=_resolve(os.getenv("CROWD_CACHE_DIR"), REPO_ROOT / "cache"),
        secrets_dir=secrets,
        google_client_secrets=_resolve(
            os.getenv("GOOGLE_CLIENT_SECRETS"), secrets / "google_client_secret.json"
        ),
        google_token_file=_resolve(
            os.getenv("GOOGLE_TOKEN_FILE"), secrets / "google_token.json"
        ),
        cors_origin_regex=os.getenv("CORS_ORIGIN_REGEX", DEFAULT_CORS_REGEX),
        models_dir=_resolve(os.getenv("CROWD_MODELS_DIR"), REPO_ROOT / "models"),
        app_password=os.getenv("APP_PASSWORD") or None,
        web_dir=_resolve(os.getenv("CROWD_WEB_DIR"), REPO_ROOT) if os.getenv("CROWD_WEB_DIR") else None,
        drive_enabled=os.getenv("CROWD_DRIVE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off"),
        seed_dir=_resolve(os.getenv("CROWD_SEED_DIR"), REPO_ROOT) if os.getenv("CROWD_SEED_DIR") else None,
    )
