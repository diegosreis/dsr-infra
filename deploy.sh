#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[infra] .env criado a partir de .env.example — edite as senhas antes de produção."
fi

echo "[infra] Subindo MySQL + MinIO + Redis + gateway..."
docker compose up -d

echo "[infra] Status:"
docker compose ps

echo ""
echo "Rede:   dsr-shared"
echo "Health: curl -s http://127.0.0.1/nginx-health"
echo "Logs:   docker compose logs -f"
