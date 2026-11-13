# Crowd Monitoring: LiDAR + Camera Fusion — one container: API + web app.
#
# Build context = the folder made by scripts/build_space.py (deploy/space/):
#   backend/   FastAPI app + pipeline + requirements.txt
#   web/       Flutter web build (BACKEND_URL=same-origin)
#   seed/      pre-processed runs (copied into /data at start-up)
#
#   docker build -t crowd-monitoring deploy/space
#   docker run -p 7860:7860 -e APP_PASSWORD=choose-one crowd-monitoring   ->  http://localhost:7860

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: H.264 transcodes and video export; libgl1/libglib: OpenCV
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run the container as user 1000
RUN useradd -m -u 1000 user
WORKDIR /app

# CPU-only PyTorch (much smaller than the CUDA build), then the rest
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
 && pip install -r backend/requirements.txt

ENV YOLO_CONFIG_DIR=/tmp/Ultralytics
# YOLO11m weights baked into the image (no download at run time)
RUN mkdir -p models \
 && python -c "from ultralytics.utils.downloads import attempt_download_asset as d; d('models/yolo11m.pt')"

COPY backend/ backend/
COPY web/ web/
COPY seed/ seed/

RUN mkdir -p /data && chown -R user:user /app /data /tmp
USER user

ENV CROWD_DATA_DIR=/data/data \
    CROWD_CACHE_DIR=/data/cache \
    CROWD_SECRETS_DIR=/data/secrets \
    CROWD_MODELS_DIR=/app/models \
    CROWD_WEB_DIR=/app/web \
    CROWD_SEED_DIR=/app/seed \
    CROWD_DRIVE_ENABLED=false \
    PORT=7860

EXPOSE 7860
# APP_PASSWORD (a secret) turns on the shared password; set it on the host, never in this file.
CMD ["sh", "-c", "python -m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port ${PORT}"]
