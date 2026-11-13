"""Assemble a ready-to-deploy folder (Docker / Hugging Face Space) in deploy/space/.

    backend/.venv/Scripts/python scripts/build_space.py                  # all processed runs
    backend/.venv/Scripts/python scripts/build_space.py --run 20261104-143316-baseline

Steps:
  1. process a copy of each chosen run (in deploy/_work/, your own run is not touched) with the
     best (notebook-default) parameters, or its own with --keep-params, so all three Live-view
     modes are cached and the server never has to run YOLO for it;
  2. build the Flutter web app for "same-origin" (the API and the app share one server);
  3. copy the backend, the web build, the Dockerfile and the chosen runs (as seed/).
The result can be built with `docker build -t crowd-monitoring deploy/space`
or uploaded as a Hugging Face Docker Space (see README, "Deployment").
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.jobs import Job  # noqa: E402
from app.params import normalize_params  # noqa: E402
from app.processing import process_steps  # noqa: E402
from app.services import Services  # noqa: E402
from app.settings import Settings, load_settings  # noqa: E402

CACHE_SKIP = {"extracted", "exports"}   # re-created on demand / not needed on the server


def warm(svc: Services, run_id: str) -> None:
    """Analyze the run (cached steps are reused) so every mode result is in the cache."""
    run = svc.store.get(run_id)
    if not (run.get("validation") or {}).get("ok"):
        raise SystemExit(f"Run {run_id} is not validated; open it in the app first.")
    job = Job(run_id, "process", process_steps(run))
    job.set_state("running")
    print(f"  processing {run_id} (cached steps are reused; YOLO only if needed) ...")
    summary = svc.processor.process(run_id, job)
    svc.store.update(run_id, results=summary, status="processed", error=None)


def copy_run(svc: Services, run_id: str, out: Path) -> None:
    src = svc.store.run_dir(run_id)
    dst = out / "seed" / "runs" / run_id
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.part", "*.tmp"))
    run = json.loads((dst / "run.json").read_text(encoding="utf-8"))
    for k in ("last_export", "live_job"):
        run.pop(k, None)
    (dst / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    cache = svc.store.cache_dir(run_id)
    if cache.is_dir():
        shutil.copytree(cache, out / "seed" / "cache" / run_id,
                        ignore=lambda d, names: [n for n in names if n in CACHE_SKIP or n.endswith((".part.mp4", ".log"))])


WORK = ROOT / "deploy" / "_work"


def common_args(ap: argparse.ArgumentParser, out: Path) -> None:
    ap.add_argument("--run", action="append", help="run id to include (repeatable); default: all processed runs")
    ap.add_argument("--out", default=str(out))
    ap.add_argument("--skip-web", action="store_true", help="reuse the existing frontend/build/web")
    ap.add_argument("--keep-params", action="store_true",
                    help="keep each run's own saved parameters (default: the best = notebook defaults)")


def prepare_runs(args: argparse.Namespace) -> tuple[Services, list[str]]:
    """Copy the chosen runs into deploy/_work and process them there (your own runs are not touched)."""
    svc = Services(load_settings())
    run_ids = args.run or [r["id"] for r in svc.store.list() if r.get("status") == "processed"]
    if not run_ids:
        raise SystemExit("No processed run to include. Process one in the app, or pass --run <id>.")
    if WORK.exists():
        shutil.rmtree(WORK)
    ws = Settings(data_dir=WORK / "data", cache_dir=WORK / "cache", secrets_dir=WORK / "secrets",
                  google_client_secrets=WORK / "none.json", google_token_file=WORK / "none.json",
                  models_dir=svc.settings.models_dir)
    ws.ensure_dirs()
    for rid in run_ids:
        shutil.copytree(svc.store.run_dir(rid), ws.runs_dir / rid, ignore=shutil.ignore_patterns("*.part", "*.tmp"))
        if svc.store.cache_dir(rid).is_dir():
            shutil.copytree(svc.store.cache_dir(rid), ws.cache_dir / rid,
                            ignore=lambda d, names: [n for n in names if n in CACHE_SKIP])
    wsvc = Services(ws)
    for rid in run_ids:
        if not args.keep_params:
            wsvc.store.update(rid, params=normalize_params({}))
        warm(wsvc, rid)
    return wsvc, run_ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common_args(ap, ROOT / "deploy" / "space")
    args = ap.parse_args()

    print("1/3  Processing a copy of the runs")
    wsvc, run_ids = prepare_runs(args)
    work = WORK

    print("2/3  Building the web app (same-origin)")
    web = ROOT / "frontend" / "build" / "web"
    if not args.skip_web:
        subprocess.run("flutter build web --release --dart-define=BACKEND_URL=same-origin",
                       cwd=ROOT / "frontend", shell=True, check=True)
    if not (web / "index.html").is_file():
        raise SystemExit("frontend/build/web is missing: run without --skip-web.")

    print(f"3/3  Assembling {args.out}")
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(ROOT / "deploy" / "Dockerfile", out / "Dockerfile")
    shutil.copy(ROOT / "deploy" / "space_README.md", out / "README.md")
    (out / ".dockerignore").write_text("**/__pycache__\n**/*.pyc\n", encoding="utf-8")
    for part in ("app", "pipeline"):
        shutil.copytree(ROOT / "backend" / part, out / "backend" / part,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(ROOT / "backend" / "requirements.txt", out / "backend" / "requirements.txt")
    shutil.copytree(web, out / "web")
    for rid in run_ids:
        copy_run(wsvc, rid, out)
    shutil.rmtree(work, ignore_errors=True)

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"\nDone: {out} ({size:.0f} MB) with run(s): {', '.join(run_ids)}")
    print("Next: see README, section 'Deployment'.")


if __name__ == "__main__":
    main()
