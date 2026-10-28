#!/bin/sh
set -eu

mkdir -p /var/cache/nginx/images /etc/nginx/sites-enabled /var/www/certbot

cp /etc/nginx/templates/nginx.conf /etc/nginx/nginx.conf
rm -f /etc/nginx/sites-enabled/*.conf

enable_site() {
  name="$1"
  cert="$2"
  src="/etc/nginx/templates/sites/${name}.conf"

  if [ ! -f "$cert" ]; then
    echo "[gateway] site ignorado (sem certificado): ${name} → ${cert}"
    return 0
  fi
  if [ ! -f "$src" ]; then
    echo "[gateway] site ignorado (sem vhost): ${name} → ${src}"
    return 0
  fi

  cp "$src" "/etc/nginx/sites-enabled/${name}.conf"
  echo "[gateway] site habilitado: ${name}"
}

enable_site marmitas /etc/letsencrypt/live/avera-marmitas.online/fullchain.pem
enable_site bangalo /etc/letsencrypt/live/bangalostudio.com.br/fullchain.pem
enable_site maciel /etc/letsencrypt/live/dentistamarciomaciel.com.br/fullchain.pem
enable_site gestaodental /etc/letsencrypt/live/gestaodental.online/fullchain.pem
enable_site morenalab /etc/letsencrypt/live/morenalab.site/fullchain.pem

# Evita falha do nginx quando o glob sites-enabled/*.conf está vazio
if ! ls /etc/nginx/sites-enabled/*.conf >/dev/null 2>&1; then
  printf '%s\n' '# placeholder — nenhum site com certificado' > /etc/nginx/sites-enabled/00-placeholder.conf
  echo "[gateway] nenhum site SSL habilitado (placeholder)"
fi

FILTER=/etc/nginx/templates/sites/gd-log-safe/run.sh
REDACTOR=/etc/nginx/templates/sites/gd-log-safe/redactor.awk

if [ ! -r "$FILTER" ] || [ ! -r "$REDACTOR" ]; then
  echo "[gateway] filtro gd-log-safe ausente ou ilegível em /etc/nginx/templates/sites/gd-log-safe/" >&2
  exit 1
fi

echo "[gateway] testando configuração (via filtro gd-log-safe)..."
if ! /bin/sh "$FILTER" nginx -e stderr -t; then
  echo "[gateway] nginx -t (via filtro) falhou. Certificados montados:" >&2
  ls -la /etc/letsencrypt/live/ 2>/dev/null || echo "(sem /etc/letsencrypt/live)" >&2
  exit 1
fi

exec /bin/sh "$FILTER" nginx -e stderr -g "daemon off;"
