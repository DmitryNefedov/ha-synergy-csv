#!/usr/bin/env bash
# End-to-end: boot a real Home Assistant container with the integration mounted,
# then drive it over its REST/WebSocket APIs (e2e/driver.py) from a second container.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${HA_IMAGE:-ghcr.io/home-assistant/home-assistant:2026.9.4}"
NET="synergy-csv-e2e"
HA="synergy-csv-e2e-ha"
WORK="$ROOT/e2e/.work"

cleanup() {
  if [ "${KEEP:-0}" != "1" ]; then
    docker rm -f "$HA" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
cleanup

# files written by the container are root-owned, so remove them from inside one
docker run --rm -v "$ROOT/e2e:/e2e" --entrypoint rm "$IMAGE" -rf /e2e/.work
mkdir -p "$WORK/config"
cat > "$WORK/config/configuration.yaml" <<'YAML'
homeassistant:
  name: Synergy E2E
  time_zone: Australia/Perth
  unit_system: metric
http:
recorder:
file_upload:
config:
onboarding:
api:
YAML
chmod -R a+rwX "$WORK"

docker network create "$NET" >/dev/null
docker run -d --name "$HA" --network "$NET" \
  -v "$WORK/config:/config" \
  -v "$ROOT/custom_components/synergy_csv:/config/custom_components/synergy_csv:ro" \
  "$IMAGE" >/dev/null

docker run --rm --network "$NET" -u "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$ROOT:/repo:ro" --entrypoint python "$IMAGE" /repo/e2e/driver.py "http://$HA:8123" \
  || { echo "--- HA log tail ---"; docker logs --tail 60 "$HA" 2>&1; exit 1; }
