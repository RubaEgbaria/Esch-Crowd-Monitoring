#!/usr/bin/env bash
# Deploy deploy/space (made by scripts/build_space.py) to Azure Container Apps.
#
#   az login                                   # once
#   APP_PASSWORD=... bash scripts/deploy_azure.sh
#
# First run creates: a resource group, a container registry (Basic), a Container Apps
# environment and the app (2 vCPU / 4 GiB, scales to zero when idle, at most 1 replica because
# jobs live in the server's memory). Later runs only rebuild the image and roll out a new revision.
# The image is built on a temporary Azure VM (deleted afterwards): Docker is not needed here.
set -euo pipefail

# A pip-installed Azure CLI on Windows (AZ_PYTHON=<venv>/Scripts/python) loses the exit codes through
# its `az` launcher, so call the module directly; otherwise use the normal `az`.
if [ -n "${AZ_PYTHON:-}" ]; then az() { "$AZ_PYTHON" -m azure.cli "$@"; }; fi

RG="${RG:-crowd-monitoring-rg}"
LOCATION="${LOCATION:-germanywestcentral}"   # Azure for Students: only a few regions are allowed
APP="${APP:-crowd-monitoring}"
ENVNAME="${ENVNAME:-crowd-monitoring-env}"
ACR="${ACR:-}"                        # registry name; default: crowdmon + a stable suffix
SRC="$(cd "$(dirname "$0")/.." && pwd)/deploy/space"
TAG="v$(date +%Y%m%d-%H%M%S)"

[ -f "$SRC/Dockerfile" ] || { echo "deploy/space is missing: run scripts/build_space.py first." >&2; exit 1; }

az extension add --name containerapp --upgrade --only-show-errors >/dev/null
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights Microsoft.Compute Microsoft.Network; do
  az provider register --namespace "$ns" --wait --only-show-errors >/dev/null
done

az group create -n "$RG" -l "$LOCATION" --only-show-errors -o none
if [ -z "$ACR" ]; then
  ACR="$(az acr list -g "$RG" --query '[0].name' -o tsv | tr -d '\r')"
  [ -n "$ACR" ] || ACR="crowdmon$(az account show --query id -o tsv | tr -d '-' | cut -c1-8)"
fi
az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null \
  || az acr create -n "$ACR" -g "$RG" -l "$LOCATION" --sku Basic --admin-enabled true --only-show-errors -o none

IMAGE="$ACR.azurecr.io/crowd-monitoring:$TAG"
ACR_PW="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv | tr -d '\r')"

# Azure for Students does not allow ACR Tasks (az acr build), so the image is built on a temporary
# VM in its own resource group, pushed to the registry, and the whole group is deleted afterwards.
build_on_vm() {
  local brg="$RG-builder" vm=crowd-builder ip
  echo "Creating a temporary build VM ($BUILD_SIZE) ..."
  az group create -n "$brg" -l "$BUILD_LOCATION" -o none
  trap 'echo "Deleting the build VM ..."; az group delete -n "'"$brg"'" --yes --no-wait' EXIT
  ip="$(az vm create -g "$brg" -n "$vm" -l "$BUILD_LOCATION" --image Ubuntu2404 --size "$BUILD_SIZE" \
        --admin-username azureuser --generate-ssh-keys --public-ip-sku Standard --os-disk-size-gb 64 \
        --query publicIpAddress -o tsv | tr -d '\r')"
  local ssh_opts=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ServerAliveInterval=30)
  for _ in $(seq 30); do ssh "${ssh_opts[@]}" "azureuser@$ip" true 2>/dev/null && break; sleep 10; done
  echo "Installing Docker on the VM ..."
  ssh "${ssh_opts[@]}" "azureuser@$ip" 'curl -fsSL https://get.docker.com | sudo sh >/dev/null 2>&1 && sudo docker version --format "Docker {{.Server.Version}}"'
  echo "Uploading the build folder ($(du -sh "$SRC" | cut -f1)) ..."
  tar czf - -C "$SRC" . | ssh "${ssh_opts[@]}" "azureuser@$ip" 'mkdir -p ctx && tar xzf - -C ctx'
  echo "Building and pushing $IMAGE ..."
  ssh "${ssh_opts[@]}" "azureuser@$ip" "echo '$ACR_PW' | sudo docker login '$ACR.azurecr.io' -u '$ACR' --password-stdin >/dev/null \
    && sudo docker build --progress=plain -t '$IMAGE' ctx 2>&1 | grep -E '^#[0-9]+ (\\[|DONE|ERROR)|ERROR' ; \
    sudo docker push '$IMAGE' | tail -1"
}
BUILD_SIZE="${BUILD_SIZE:-Standard_B2als_v2}"            # 2 vCPU / 4 GB
BUILD_LOCATION="${BUILD_LOCATION:-polandcentral}"       # B-series VMs are offered there for students
build_on_vm
az acr repository show -n "$ACR" --image "crowd-monitoring:$TAG" -o none \
  || { echo "The image was not pushed; see the build output above." >&2; exit 1; }

if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  [ -n "${APP_PASSWORD:-}" ] && az containerapp secret set -n "$APP" -g "$RG" \
      --secrets "app-password=$APP_PASSWORD" -o none
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" -o none
else
  : "${APP_PASSWORD:?set APP_PASSWORD for the first deployment}"
  az containerapp env show -n "$ENVNAME" -g "$RG" -o none 2>/dev/null \
    || az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOCATION" --only-show-errors -o none
  az containerapp create -n "$APP" -g "$RG" --environment "$ENVNAME" \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-username "$ACR" --registry-password "$ACR_PW" \
    --target-port 7860 --ingress external \
    --cpu 2 --memory 4Gi --min-replicas 0 --max-replicas 1 \
    --secrets "app-password=$APP_PASSWORD" --env-vars "APP_PASSWORD=secretref:app-password" \
    --only-show-errors -o none
fi

URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "Deployed: $URL"
