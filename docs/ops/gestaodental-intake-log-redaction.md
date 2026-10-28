# Ops: filtro de stderr dos convites Gestão Dental (gateway)

**Não executar em produção sem autorização.** Manter
`FEATURE_PATIENT_INTAKE_PUBLIC=false` até prova positiva nas três camadas
(app web/API + este gateway) em janela autorizada.

## Implementado neste repositório

- `nginx/sites/gd-log-safe/run.sh` + `redactor.awk` — cópias canônicas do app
  (gestaodental `nginx/log-safe/*`).
- `nginx/nginx.conf` — `error_log stderr warn;` no contexto principal; sem
  `access_log` http-level com `$request`/`$http_referer`.
- `scripts/entrypoint.sh` — exige o filtro, roda `nginx -t` **via** filtro e
  inicia com:
  `exec /bin/sh /etc/nginx/templates/sites/gd-log-safe/run.sh nginx -e stderr -g "daemon off;"`

Compose monta `./nginx/sites` → `/etc/nginx/templates/sites` (o diretório
`gd-log-safe/` entra nesse mount; não usa extensão `.conf`).

O deploy do app continua sincronizando só `nginx/site.conf` (access log
sanitizado). **Reload sozinho não instala o wrapper** — é preciso recriar o
serviço do gateway.

## Perda localizada de observabilidade

Eventos de `error_log` cujo texto contenha rota sensível (`/convite/`,
`/api/v1/public/patient-intake/`), `%` ou `?` viram uma linha
`[nginx] diagnostic context [redacted] (...)`. Diagnósticos comuns sem esse
contexto seguem intactos. A URI encaminhada à aplicação **não** muda.

## Procedimento futuro (não executado por este PR)

### 1. Backup com caminho único

```bash
INFRA=/opt/dsr-infra
BACKUP=$(mktemp -d /var/lib/dsr-infra/nginx-log-backup.XXXXXX)
chmod 700 "$BACKUP"
cp -a "$INFRA/nginx/nginx.conf" "$BACKUP/template.conf"
cp -a "$INFRA/scripts/entrypoint.sh" "$BACKUP/entrypoint.sh"
cp -a "$INFRA/nginx/sites/gestaodental.conf" "$BACKUP/site.conf"
cp -a "$INFRA/nginx/sites/gd-log-safe" "$BACKUP/log-safe"
docker cp vps-gateway:/etc/nginx/nginx.conf "$BACKUP/active.conf"
docker cp vps-gateway:/etc/nginx/sites-enabled/gestaodental.conf "$BACKUP/active-site.conf"
printf 'Guardar este caminho exato para recuperação: %s\n' "$BACKUP"
```

### 2. Testar template e conferir configuração ativa

Após merge/pull da infra (sem recriar ainda):

```bash
docker exec vps-gateway /bin/sh /etc/nginx/templates/sites/gd-log-safe/run.sh \
  nginx -e stderr -t -c /etc/nginx/templates/nginx.conf
# Conferir includes/error_log na fonte e no ativo (não dumpar config completa).
docker exec vps-gateway nginx -T 2>/dev/null | grep -E 'error_log|access_log|gd_intake|gd-log-safe' | head
```

### 3. Recriar SOMENTE o gateway (identidade Compose real)

Não herdar o projeto `ortoimplante` do app.

```bash
PROJECT=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' vps-gateway)
SERVICE=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' vps-gateway)
WORKDIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' vps-gateway)
CONFIGS=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' vps-gateway)
[ -n "$PROJECT" ] && [ -n "$SERVICE" ] && [ -d "$WORKDIR" ] && [ -n "$CONFIGS" ] || exit 1
[ "$PROJECT" != ortoimplante ] || exit 1
IFS=',' read -r -a configs <<< "$CONFIGS"
compose_args=()
for file in "${configs[@]}"; do
  [ -f "$file" ] || exit 1
  compose_args+=(-f "$file")
done
cd "$WORKDIR"
docker compose "${compose_args[@]}" -p "$PROJECT" up -d --no-deps --force-recreate "$SERVICE"
```

Confirmar health (`/nginx-health`), HTTP dos sites e processo do wrapper
(`docker top vps-gateway`).

### 4. Prova com marcador fictício (três camadas, logs delimitados)

```bash
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MARKER="GD_FAKE_$(openssl rand -hex 12)"
REF="https://gestaodental.online/convite/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/convite/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/api/v1/public/patient-intake/$MARKER?repeat=$MARKER"
curl --max-time 15 -sS -o /dev/null -H "Referer: $REF" \
  "https://gestaodental.online/intake-log-probe-missing.png?repeat=$MARKER"
sleep 1
for container in vps-gateway ortoimplante-web ortoimplante-api; do
  file="$BACKUP/probe-$container.log"
  docker logs --since "$SINCE" "$container" > "$file" 2>&1
  if grep -Fq "$MARKER" "$file"; then
    echo "FALHA: marcador bruto em $container"; exit 1
  fi
done
# Prova positiva no gateway: evento sanitizado no intervalo
grep -F 'diagnostic context [redacted]' "$BACKUP/probe-vps-gateway.log" \
  || grep -E 'GET /(convite|api/v1/public/patient-intake)/\[redacted\]' "$BACKUP/probe-vps-gateway.log" \
  || { echo "FALHA: sem prova positiva sanitizada"; exit 1; }
```

Não imprimir logs de produção. Só então considerar habilitar a feature pelo
fluxo de config existente.

## Recuperação

Usar **exatamente** `$BACKUP` guardado (sem wildcard):

```bash
cp -a "$BACKUP/template.conf" "$INFRA/nginx/nginx.conf"
cp -a "$BACKUP/entrypoint.sh" "$INFRA/scripts/entrypoint.sh"
cp -a "$BACKUP/site.conf" "$INFRA/nginx/sites/gestaodental.conf"
cp -a "$BACKUP/log-safe/." "$INFRA/nginx/sites/gd-log-safe/"
cd "$WORKDIR"
docker compose "${compose_args[@]}" -p "$PROJECT" up -d --no-deps --force-recreate "$SERVICE"
```

## Teste local (desenvolvimento)

```bash
python3 scripts/tests/gd-log-safe-gateway-test.py
```

Exige Docker. Não é substituto da prova em produção.
