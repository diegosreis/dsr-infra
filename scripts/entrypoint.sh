#!/bin/sh
set -eu

mkdir -p /var/cache/nginx/images /etc/nginx/sites-enabled /var/www/certbot

cp /etc/nginx/templates/nginx.conf /etc/nginx/nginx.conf
rm -f /etc/nginx/sites-enabled/*.conf

enable_site() {
  name="$1"
  cert="$2"

  if [ -f "$cert" ]; then
    cp "/etc/nginx/templates/sites/${name}.conf" "/etc/nginx/sites-enabled/${name}.conf"
    echo "[gateway] site habilitado: ${name}"
  else
    echo "[gateway] site ignorado (sem certificado): ${name} → ${cert}"
  fi
}

enable_site marmitas /etc/letsencrypt/live/avera-marmitas.online/fullchain.pem
enable_site bangalo /etc/letsencrypt/live/bangalostudio.com.br/fullchain.pem

nginx -t
exec nginx -g "daemon off;"
