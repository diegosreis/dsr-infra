# Ops: filtro de stderr dos convites Gestão Dental (gateway)

**Não executar em produção sem autorização.** Manter
`FEATURE_PATIENT_INTAKE_PUBLIC=false` até prova positiva nas três camadas
(app web/API + este gateway) em janela autorizada.

## Implementado neste repositório

- `nginx/sites/gd-log-safe/run.sh` + `redactor.awk` — cópias canônicas do app
  (gestaodental `nginx/log-safe/*` @ `4142d65`).
- `nginx/sites/gestaodental.conf` — sincronizado do app `nginx/site.conf` @
  `4142d65` (PR #36). Antes ausente neste git (só via deploy do app).
- `nginx/nginx.conf` — `error_log stderr warn;` no contexto principal; sem
  `access_log` http-level com `$request`/`$http_referer`.
- `scripts/entrypoint.sh` — exige o filtro, roda `nginx -t` **via** filtro e
  inicia com:
  `exec /bin/sh /etc/nginx/templates/sites/gd-log-safe/run.sh nginx -e stderr -g "daemon off;"`

Compose monta `./nginx/sites` → `/etc/nginx/templates/sites` (o diretório
`gd-log-safe/` entra nesse mount; não usa extensão `.conf`).

O deploy do app continua podendo sincronizar `nginx/site.conf` para o template
do vhost. **Reload sozinho não instala o wrapper** — é preciso recriar o
serviço do gateway.

## Perda localizada de observabilidade

Eventos de `error_log` cujo texto contenha rota sensível (`/convite/`,
`/api/v1/public/patient-intake/`), `%` ou `?` viram uma linha
`[nginx] diagnostic context [redacted] (...)`. Diagnósticos comuns sem esse
contexto seguem intactos. A URI encaminhada à aplicação **não** muda.

## Procedimento futuro (não executado por este PR)

Ordem: **backup →** atualizar checkout da infra → testar template → recriar
gateway → prova nas três camadas. Interromper se qualquer etapa obrigatória
falhar.

### 1. Backup com caminho único (ANTES de atualizar o checkout)

```bash
#!/usr/bin/env bash
set -euo pipefail

INFRA=/opt/dsr-infra
PARENT=/var/lib/dsr-infra
mkdir -p "$PARENT"
chmod 750 "$PARENT"
BACKUP=$(mktemp -d "$PARENT/nginx-log-backup.XXXXXX")
chmod 700 "$BACKUP"

cp -a "$INFRA/nginx/nginx.conf" "$BACKUP/template.conf"
cp -a "$INFRA/scripts/entrypoint.sh" "$BACKUP/entrypoint.sh"
cp -a "$INFRA/nginx/sites/gestaodental.conf" "$BACKUP/site.conf"

if [ -d "$INFRA/nginx/sites/gd-log-safe" ]; then
  printf 'yes\n' > "$BACKUP/log-safe-existed-before"
  cp -a "$INFRA/nginx/sites/gd-log-safe" "$BACKUP/log-safe"
else
  printf 'no\n' > "$BACKUP/log-safe-existed-before"
fi

docker cp vps-gateway:/etc/nginx/nginx.conf "$BACKUP/active.conf"
docker cp vps-gateway:/etc/nginx/sites-enabled/gestaodental.conf "$BACKUP/active-site.conf"

# Falha fechada: todos os artefatos obrigatórios devem existir
test -f "$BACKUP/template.conf"
test -f "$BACKUP/entrypoint.sh"
test -f "$BACKUP/site.conf"
test -f "$BACKUP/active.conf"
test -f "$BACKUP/active-site.conf"
test -f "$BACKUP/log-safe-existed-before"
if [ "$(cat "$BACKUP/log-safe-existed-before")" = yes ]; then
  test -d "$BACKUP/log-safe"
fi

printf 'Guardar este caminho exato para recuperação: %s\n' "$BACKUP"
```

Só depois: `git pull` / checkout da infra no `$INFRA`.

### 2. Testar template e conferir configuração ativa

```bash
set -euo pipefail
docker exec vps-gateway /bin/sh /etc/nginx/templates/sites/gd-log-safe/run.sh \
  nginx -e stderr -t -c /etc/nginx/templates/nginx.conf
# Conferir includes/error_log na fonte e no ativo (não dumpar config completa).
docker exec vps-gateway nginx -T 2>/dev/null | grep -E 'error_log|access_log|gd_intake|gd-log-safe' | head
```

### 3. Recriar SOMENTE o gateway (identidade Compose real)

Não herdar o projeto `ortoimplante` do app.

```bash
set -euo pipefail
PROJECT=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' vps-gateway)
SERVICE=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' vps-gateway)
WORKDIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' vps-gateway)
CONFIGS=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' vps-gateway)
[ -n "$PROJECT" ] && [ -n "$SERVICE" ] && [ -d "$WORKDIR" ] && [ -n "$CONFIGS" ]
[ "$PROJECT" != ortoimplante ]
IFS=',' read -r -a configs <<< "$CONFIGS"
compose_args=()
for file in "${configs[@]}"; do
  [ -f "$file" ]
  compose_args+=(-f "$file")
done
cd "$WORKDIR"
docker compose "${compose_args[@]}" -p "$PROJECT" up -d --no-deps --force-recreate "$SERVICE"
```

Confirmar health (`/nginx-health`), HTTP dos sites e processo do wrapper
(`docker top vps-gateway`).

### 4. Prova positiva nas três camadas (marcador fictício)

Logs vazios ou só “marcador ausente” **não** bastam. Em cada container exigir
consulta OK + ausência do marcador + access log sanitizado da rota +
método/status/`rt=`.

```bash
set -euo pipefail
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MARKER="GD_FAKE_$(openssl rand -hex 12)"
REF="https://gestaodental.online/convite/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/convite/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/api/v1/public/patient-intake/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/?probe=$MARKER"
sleep 1

assert_layer() {
  local container=$1
  local path_pattern=$2
  local file="$BACKUP/probe-$container.log"
  docker logs --since "$SINCE" "$container" > "$file" 2>&1
  test -s "$file"
  if grep -Fq "$MARKER" "$file"; then
    echo "FALHA: marcador bruto em $container"; exit 1
  fi
  # Prova positiva: access log sanitizado (não basta diagnostic [redacted])
  grep -E "\"(GET|HEAD|POST) ${path_pattern} HTTP/[0-9.]+\" [0-9]{3} .*rt=" "$file" >/dev/null \
    || { echo "FALHA: sem access log sanitizado com método/status/rt= em $container"; exit 1; }
}

assert_layer vps-gateway '/(convite|api/v1/public/patient-intake)/\[redacted\]'
assert_layer ortoimplante-web '/convite/\[redacted\]'
assert_layer ortoimplante-api '/api/v1/public/patient-intake/\[redacted\]'
```

Não imprimir logs de produção. Só então considerar habilitar a feature pelo
fluxo de config existente.

## Recuperação

Usar **exatamente** `$BACKUP` guardado (sem wildcard):

```bash
set -euo pipefail
cp -a "$BACKUP/template.conf" "$INFRA/nginx/nginx.conf"
cp -a "$BACKUP/entrypoint.sh" "$INFRA/scripts/entrypoint.sh"
cp -a "$BACKUP/site.conf" "$INFRA/nginx/sites/gestaodental.conf"
if [ "$(cat "$BACKUP/log-safe-existed-before")" = yes ]; then
  mkdir -p "$INFRA/nginx/sites/gd-log-safe"
  cp -a "$BACKUP/log-safe/." "$INFRA/nginx/sites/gd-log-safe/"
else
  # Primeira instalação: não havia filtro; remova só se a recuperação exigir o estado anterior
  rm -rf "$INFRA/nginx/sites/gd-log-safe"
fi
cd "$WORKDIR"
docker compose "${compose_args[@]}" -p "$PROJECT" up -d --no-deps --force-recreate "$SERVICE"
```

## Teste local (desenvolvimento)

```bash
python3 scripts/tests/gd-log-safe-gateway-test.py
```

Exige Docker. Não é substituto da prova em produção.
