# Esch-Crowd-Monitoring

People detection and counting with a **Blickfeld Qb2 LiDAR** and a **camera** (YOLO11m), and the
fusion of the two. AE3S Lab, University of Luxembourg.

The repository has two parts:

- **Research notebooks** (repository root): the reference implementation of every algorithm.
- **Web app** (`backend/` + `frontend/`): give it a recording (a Google Drive folder or uploaded
  files), and it runs the notebook pipeline and replays the result as if the sensors were live.
  The app runs locally on your laptop.

> **Status: Phase 3 of 5.**
> - Phase 1: runs, Google Drive sign-in, folder link/path resolution, file auto-detection,
>   downloads and uploads with progress, input validation.
> - Phase 2: the processing pipeline (LiDAR, YOLO11m, time alignment, fusion) with live progress
>   on the run page, plus acceptance tests against the notebook.
> - Phase 3: the **Live view**: choose a mode → Run → replay with detections. It also includes the
>   parameters drawer, the results panel and the exports.
> - Next: "Run YOLO live" during replay and privacy mode.

---

## 1. Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11 | for the backend |
| Flutter | stable channel (3.47 or newer) | for the web frontend |
| Google Chrome | any recent | the app runs in Chrome |
| ffmpeg | optional | converts the sensor UI recording to H.264; the `imageio-ffmpeg` package is used when it is not installed |
| NVIDIA GPU | optional | YOLO uses it automatically if the CUDA build of torch is installed; otherwise CPU (~0.4 s/frame) |
| A Google account | | only for the Google Drive tab |

## 2. Setup (once)

From the repository root:

**Backend (Windows PowerShell)**

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
```

**Backend (macOS / Linux)**

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

Notes:

- **GPU:** to run YOLO on an NVIDIA GPU, install the CUDA build of torch *before* the
  requirements (see <https://pytorch.org/get-started/locally/>).
- **OpenCV:** the requirements use `opencv-python`, the package `ultralytics` depends on. Do not
  also install `opencv-python-headless`: both provide `cv2` and overwrite each other.
- **YOLO weights:** `yolo11m.pt` (39 MB) is downloaded into `models/` the first time a run is
  processed. You can also copy your own copy there.

**Frontend**

```bash
cd frontend
flutter pub get
```

Optional: copy `.env.example` to `.env` to change where data, cache and secrets are stored.

## 3. Google Drive setup (OAuth, once)

The app reads your Drive folders with **read-only** access, through your own Google account. The
folder does **not** need to be public. You need your own OAuth "Desktop app" client:

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project (top
   bar → project picker → **New project**, e.g. `crowd-monitoring`), then select it.
2. **Enable the Drive API**: menu → **APIs & Services → Library** → search **Google Drive API**
   → **Enable**.
3. **Configure the consent screen**: menu → **Google Auth Platform** (called *OAuth consent
   screen* in older consoles) → **Get started**.
   - App name: `Crowd Monitoring`; user support email: your email.
   - Audience: **External** (or **Internal** if your university Google Workspace allows it).
   - Contact email: your email → **Create**.
4. **Add yourself as a test user**: **Google Auth Platform → Audience → Test users → Add users** →
   your Google address (and those of lab members who will use it). While the app is in
   *Testing* mode, only test users can sign in.
5. **Create the client**: **Google Auth Platform → Clients → Create client**.
   - Application type: **Desktop app** (not *Web application*).
   - Name: `Crowd Monitoring local` → **Create**.
6. **Download the JSON** of the new client (download icon, or *Download JSON* in the dialog) and
   save it as:

   ```
   secrets/google_client_secret.json
   ```

   (`secrets/` is in `.gitignore`: it is never committed.)
7. Start the app, open **New run → Google Drive → Sign in with Google**. A Google tab opens:
   - Choose your account.
   - Google shows *"Google hasn't verified this app"* (expected for a personal Testing app): click
     **Continue**.
   - Allow **See and download all your Google Drive files** (read-only).

   The tab then says you can close it, and the app shows *Signed in as …*. The token is stored in
   `secrets/google_token.json`.

Notes:

- In *Testing* mode Google expires the sign-in after **7 days**. The app then asks you to sign in
  again.
- **Sign out** (in the Drive tab) deletes the local token. To revoke access completely:
  <https://myaccount.google.com/permissions>.
- If sign-in says *access blocked* with your university account, your Workspace may block
  unverified apps. Use the **Internal** audience inside the university project, or a personal
  Google account that has access to the folder.

## 4. Run the app

**One command** (starts the backend and opens the app in Chrome; Ctrl+C stops both):

```powershell
.\scripts\start.ps1          # Windows PowerShell
```

```bash
./scripts/start.sh           # macOS / Linux / Git Bash
```

**Or in two terminals**:

```bash
# 1) backend on http://localhost:8000
backend/.venv/Scripts/python -m uvicorn app.main:create_app --factory --app-dir backend --port 8000
# 2) frontend
cd frontend
flutter run -d chrome --dart-define=BACKEND_URL=http://localhost:8000
```

The backend URL defaults to `http://localhost:8000`; change it with `--dart-define=BACKEND_URL=...`.
The API documentation is at <http://localhost:8000/docs>.

## 5. Using the app

**Runs** lists past runs with their status. From there you can open, rerun or delete a run.

**New run** has two tabs:

- **Google Drive**: paste either
  - a folder share link (`https://drive.google.com/drive/folders/…`), or
  - a path, e.g. `My Drive/Crowd-Density-Monitoring/Code/baseline`. The Colab form
    (`/content/drive/My Drive/…`, the `DRIVE_ROOT` of the notebooks) and `Shared drives/<drive>/…`
    also work.

  **Find files** lists the folder and picks the inputs automatically:
  - **LiDAR recording**: the `.zip`, e.g. `192.168.137.36_2026-09-08_11-33-52.zip`.
  - **Camera video**: the `.mp4` whose name does not contain "lidar", e.g. `raw-vid.mp4`.
  - **Sensor UI recording** (optional): the `.mp4` containing "lidar", e.g. `lidar_top_view.mp4`.
    It is shown as a reference only and is not synchronised.
  - Everything else, including the `outputs/` subfolder, is ignored.

  You can change the selection before analysing. The files are downloaded to `data/runs/<run_id>/`.
- **Upload files**: choose the Qb2 `.zip` and the camera video (required), and optionally the
  sensor UI recording.

**Ground truth** (optional) is a list of `(start, end, people)` segments in seconds of video time,
as in the notebooks. `T` is the end of the video and `T-x` is x seconds before the end. Editable
presets:

| Preset | Segments | Source |
|---|---|---|
| baseline | (0, 5, 5), (5, T-4, 6), (T-4, T, 5) | `sensors_fusion.ipynb`, CONFIG |
| with_items | (0, 5, 4), (5, T-3, 6), (T-3, T, 5) | `lab_experiment_pedestrian_camera.ipynb`, VIDEO_CONFIGS |
| lights_off | (0, 6, 5), (6, T-3, 6), (T-3, T, 5) | same |
| less_crowded | (0, T, 5) | same |

**Analyze** downloads or uploads the files, checks them, then processes the run. A run whose inputs
are already checked shows an **Analyze** button on its page.

The checks:

- the zip contains `frame_*.pb` and the three `perceptPipeline*.json` files;
- the JSON files parse, and every frame parses with `blickfeld_qb2`. Empty frames are kept as
  0 points. The run fails only if there are no frames, or more than 10% cannot be parsed;
- the videos can be decoded;
- the ground truth fits the video duration.

Processing runs these steps:

| Step | What it does |
|---|---|
| Extract the LiDAR zip | into `cache/<run_id>/extracted/` |
| LiDAR pipeline | background subtraction, floor frame, zone filter, DBSCAN + KMeans split, tracking, 1 s rolling median (`Qb2_people_counting` / `sensors_fusion` cell 9). Keeps the foreground points, clusters and track IDs of every frame |
| YOLO11m detection | every video frame, GPU if available, imgsz 640. All person boxes with conf > 0.10 are stored, so the confidence threshold (0.25 by default) can change later without running YOLO again |
| Transcode the sensor UI recording | to H.264 with ffmpeg (the recording uses `fmp4`, which browsers cannot play) |
| Time alignment | 10 Hz grid on the video timeline; LiDAR/YOLO lag by cross-correlation (±5 s) |
| Fusion | Mean, WAvg, Stack-LinReg, Stack-GBT, Conf-aware GBT; blocked 5-fold CV, out-of-fold predictions only; Auto = lowest CV MAE |

The run page shows:

- the device (CPU or GPU);
- an overall progress bar;
- each step: waiting, running, done or failed. The running step shows e.g.
  `frame 120 / 454 · 26% · 0:42 elapsed · ETA 2 min`;
- if a step fails, which step and why, with a **Retry** button.

The job runs on the backend, so you can close or refresh the page. Each step's results are cached:
**Rerun** and **Retry** reuse every step whose inputs and parameters did not change.

**Time alignment, the one change from the notebook.** The notebook shifts the LiDAR counts with
`np.roll`, which wraps the end of the signal around to the start. The app shifts the LiDAR
*timestamps* instead (`t_video = t_lidar − lag`), and grid points that the shifted LiDAR
recording does not cover have no LiDAR value. Fusion and metrics use the overlap.

On baseline:
- the LiDAR recording is 36.3 s and the video 43.2 s;
- lag = −5.00 s (r = 0.42), so the LiDAR covers 5.0–41.3 s, i.e. 363 of the 432 grid points;
- the best lag is at the edge of the ±5 s search window; the page flags this.

Problems are reported with a clear message; nothing is ever replaced by synthetic data.

### Live view

Open a run and click **Live view**.

**Choose a mode, then Run.** Run computes only what the mode needs:

| Mode | Runs | View |
|---|---|---|
| LiDAR only | the LiDAR pipeline | bird's-eye view: a box per detected person with track ID, head height and a fading trail |
| Camera only (YOLO11m) | YOLO + an H.264 copy of the camera video | the video with a green box and confidence on every YOLO person detection |
| Fusion (Stack-GBT) | LiDAR + YOLO (cached results reused), time alignment, Stack-GBT with blocked 5-fold CV and out-of-fold predictions | both views side by side on one timeline, with the fused count shown large above them. Needs ground truth |

- **Caching.** Every result is cached by mode + parameter hash, so switching back to a mode that
  was already run is instant. Progress shows the step, frame X / N, % and ETA.
- **Replay** runs in the browser:
  - the video plays and the overlays are drawn from the stored per-frame results, so nothing is
    processed during replay;
  - the controls are play/pause, frame step, ±1 s, the scrubber, speed 0.25x–2x and loop;
  - keyboard: Space plays/pauses, ←/→ steps one frame, Shift + ←/→ jumps one second.
- **Overlays** follow the style of the notebook's fusion_demo (cell 15):
  - the ROI of the floor homography, toggleable and labelled "approximate calibration";
  - the "GT phase" label at the top centre;
  - one HUD with t, GT and the counts of the active mode.
- **LiDAR placement.** The LiDAR is placed on the video timeline by the lag. The lag is estimated
  with the YOLO counts at the notebook's confidence (0.25), so moving the confidence slider never
  moves the LiDAR. If YOLO has never been run on the video, LiDAR only uses your manual offset,
  or 0 with a warning.
- **Parameters** (drawer):
  - each parameter has a slider, a number input and a tooltip;
  - a coloured tick and a "Best" badge mark the notebook default (eps = 0.10 won the eps sweep);
  - a changed value is highlighted in amber, with "Reset to best" per parameter, per group and
    for all;
  - LiDAR changes show "Parameters changed, run again" instead of rerunning;
  - the YOLO confidence filters the boxes instantly;
  - the parameters are remembered per run.
- **Results panel:**
  - live counts;
  - the count over time vs GT, with a playhead (click the chart to seek);
  - the counting_metrics of every mode run with the current parameters, side by side;
  - mean latency;
  - CSV / JSON export of the per-frame results;
  - **Export annotated video**: an H.264 .mp4 of the current view with its overlays, like
    fusion_demo.mp4.

**Note on the occupancy zone of the baseline recording.**
- The z axis of the Qb2 `mapFromLidar` transform is 59° off the floor normal fitted from the
  background.
- The notebook's zone test (`in_zone_xy`, z ignored) therefore keeps a slanted volume, not a
  vertical column. The app reproduces the notebook exactly.
- The bird's-eye view draws the zone's footprint at 1.0 m (dashed), and at 0 m and 1.7 m (dotted).
- Re-checking the sensor location in the Qb2 web interface (lidar-config-doc.md §8) would make the
  zone vertical.

## 6. Where things are stored

| Folder | Content | Committed? |
|---|---|---|
| `data/runs/<run_id>/` | input files + `run.json` (description, status, results summary) | no |
| `cache/<run_id>/` | `extracted/`, `lidar/<params hash>/` (per-frame counts, clusters, points), `yolo/detections.json`, `media/` (H.264 copies), `modes/<mode>-<hash>.json` (Live view results), `exports/` (annotated videos), `manifest.json` (step cache keys) | no |
| `models/` | YOLO weights | no |
| `secrets/` | Google OAuth client and token | no |
| `tests/fixtures/` | baseline inputs and notebook outputs for the acceptance tests | no |

There is no database: deleting a run deletes its two folders.

## 7. Tests

```bash
backend/.venv/Scripts/python -m pytest      # Windows
backend/.venv/bin/python -m pytest          # macOS / Linux
```

Put the baseline recording (the Qb2 `.zip` and `raw-vid.mp4`) in `tests/fixtures/baseline/` to
run the real-data and **acceptance** tests (`tests/test_acceptance_baseline.py`):

- The first run processes the baseline into `tests/fixtures/baseline/_work/`, which takes about
  3 minutes on CPU because of YOLO. Later runs reuse it.
- The tests compare the app with the values printed in `sensors_fusion.ipynb`:
  - the LiDAR counts and means;
  - the YOLO counts;
  - the lag;
  - the grid statistics;
  - the single-source blocked-CV MAE;
  - the counting metrics.
- When the notebook output files `lidar_counts.json`, `yolo_detections.json` and
  `ensemble_results.csv` are in the same folder, the tests also compare every frame.
- An agreement report is written to `tests/fixtures/baseline/_work/acceptance_report.json`.

The outputs saved in the notebook were produced with the first baseline segment ending at 4.0 s
(its `df.describe()` gives a mean ground truth of 5.814815 = 2512/432). The acceptance tests use
that ground truth when they compare with those outputs.

## 8. Deployment (a server your supervisor can open any time)

The app is deployed as **one Docker container**: the backend also serves the web app, so there is
no separate frontend host and nothing to configure for cross-site requests.

**Hosted settings** (environment variables, all set by the Dockerfile except the password):

| Variable | Meaning |
|---|---|
| `APP_PASSWORD` | Shared password for the whole site (browser login box; any user name). **Set it as a secret on the host.** |
| `CROWD_DRIVE_ENABLED=false` | Hides Google Drive import (its sign-in only works on your own computer); Upload still works. |
| `CROWD_WEB_DIR` | Folder of the built web app served at `/`. |
| `CROWD_SEED_DIR` | Pre-processed runs copied into the data folder at start-up, so they survive restarts. |

**1. Build the deploy folder** (on your laptop, from the repository root):

```powershell
backend\.venv\Scripts\python scripts\build_space.py
```

By default it takes every processed run (`--run <id>` picks some). It makes sure each run is fully processed (all three Live-view modes cached, so the server never
re-runs YOLO for it), builds the web app and writes everything to `deploy/space/` (not committed:
it contains the recording).

**2a. Test it with Docker on your laptop** (optional, needs Docker Desktop):

```powershell
docker build -t crowd-monitoring deploy/space
docker run -p 7860:7860 -e APP_PASSWORD=choose-one crowd-monitoring
```

Then open <http://localhost:7860>.

**2b. Put it online on Azure Container Apps** (used now; works with Azure for Students credit):

```bash
# once: Azure CLI (pip install avoids the admin installer) and sign-in to the student directory
python -m venv ~/.azure-cli-venv && ~/.azure-cli-venv/Scripts/python -m pip install azure-cli
~/.azure-cli-venv/Scripts/python -m azure.cli login --tenant <directory>.onmicrosoft.com

# every deployment (Git Bash, from the repository root)
AZ_PYTHON=~/.azure-cli-venv/Scripts/python APP_PASSWORD=<password> bash scripts/deploy_azure.sh
```

The script creates (first time) a resource group, a Basic container registry (about $5/month) and
the Container App (2 vCPU / 4 GiB, **scales to zero** when nobody uses it, so it costs only while
it is used; the first visit after a pause takes ~30–60 s). Azure for Students does not allow
building images in the registry (`az acr build`), so the script builds the image on a temporary VM
in Poland Central and deletes it afterwards (a few cents). Later runs rebuild the image and roll
out a new version; leave out `APP_PASSWORD` to keep the current one. Student subscriptions only
allow some regions (Germany West Central, Poland Central, France Central, Austria East, Israel
Central). Runs uploaded on the server are lost when it restarts or scales to zero; the seeded runs
come back.

**2c. Or on Hugging Face Spaces** (Docker Spaces need a PRO account, $9/month):

1. On <https://huggingface.co/new-space>: choose a name, SDK **Docker** (blank), hardware
   **CPU basic** (free with PRO), and visibility **Protected**. The app is then reachable by
   link, while its files (including the recording) stay private.
2. In the Space: **Settings → Variables and secrets → New secret**: `APP_PASSWORD` = a password
   for your supervisor.
3. Upload the folder:
   ```powershell
   backend\.venv\Scripts\python -m pip install -U huggingface_hub
   hf auth login
   hf upload <your-user>/<space-name> deploy/space . --repo-type space
   ```
   The Space builds the image (about 10 minutes the first time) and starts it.
4. Send your supervisor the direct link `https://<your-user>-<space-name>.hf.space` and the
   password. Use the direct link: the login box does not work inside the huggingface.co page frame.

Notes:
- The free disk of a Space is wiped on restart: the seeded runs come back automatically, runs
  uploaded on the server do not.
- The Space sleeps when unused and wakes on the next visit (about a minute).
- YOLO runs on 2 CPUs there: processing a new 45 s video takes several minutes.

## 9. Repository layout

```
backend/
  app/            FastAPI app: runs, jobs, processing (modes, Analyze, export), parameters, Google Drive, uploads, validation
  pipeline/       ports of the notebook algorithms: config, qb2_io, lidar, camera, sync, fusion, metrics, render
  requirements.txt
frontend/         Flutter web app (Riverpod, go_router, Inter font); lib/live/ = Live view
scripts/          start.ps1 / start.sh, build_space.py (deployment folder)
deploy/           Dockerfile and Hugging Face Space README
tests/            pytest suite
*.ipynb           research notebooks (reference implementation, not modified by the app)
lidar-config-doc.md   how to connect the Qb2 and record a scene
```

## 10. Notebooks

| Notebook | Role |
|---|---|
| `sensors_fusion.ipynb` | Main reference: LiDAR + YOLO + camera-app fusion on the baseline recording |
| `Qb2_people_counting.ipynb` | Qb2 LiDAR pipeline (background subtraction, DBSCAN, tracking) |
| `lab_experiment_pedestrian_camera.ipynb` | YOLO on the lab videos; ground-truth presets |
| `people_counter_from_vid.ipynb`, `vid_rectangle_cleaner.ipynb` | Camera-app counting and video cleaning (not used by the app) |
| `LiDAR_pedestrian_detection.ipynb`, `Camera_only_pedestrian_detection.ipynb` | Experiments on other datasets (not used by the app) |
| `Complete_sensor_fusion.ipynb` | Earlier fusion draft (not used by the app) |

Recording procedure for the sensor: [lidar-config-doc.md](lidar-config-doc.md).
