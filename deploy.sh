#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

NETWORK_NAME="${SHARED_NETWORK_NAME:-marmitas-catalog_marmitas-network}"

if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "[gateway] Criando rede compartilhada: $NETWORK_NAME"
  docker network create "$NETWORK_NAME"
fi

echo "[gateway] Subindo proxy reverso (portas 80/443)..."
docker compose up -d

echo "[gateway] Status:"
docker compose ps

echo ""
echo "Health: curl -s http://127.0.0.1/nginx-health"
echo "Logs:   docker compose logs -f gateway"
