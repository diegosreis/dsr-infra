# dsr-infra

Gateway e infraestrutura compartilhada da VPS (Diego Reis).

Dono das portas **80/443**. As apps (Marmitas, Bangalô, …) só escutam na rede Docker interna.

## Arquitetura

```text
Internet
   │
vps-gateway (:80/:443)          ← este repo
   ├─ avera-marmitas.online     → marmitas-app:3000
   └─ bangalostudio.com.br      → bangalo-app:3000
              │
   rede: marmitas-catalog_marmitas-network
              │
   mysql · minio · redis · apps   ← repos das aplicações
```

| Repo | Papel |
|------|--------|
| **dsr-infra** | Gateway Nginx + vhosts |
| [marmitas-catalog](https://github.com/diegosreis/marmitas-catalog) | App + MySQL + MinIO + Redis |
| [Bangalo-studio](https://github.com/diegosreis/Bangalo-studio) | App Bangalô |

## Na VPS

```bash
cd /opt
git clone https://github.com/diegosreis/dsr-infra.git
cd dsr-infra

# Rede compartilhada (criada pelo compose do Marmitas; se ainda não existir:)
docker network create marmitas-catalog_marmitas-network 2>/dev/null || true

chmod +x deploy.sh scripts/entrypoint.sh
./deploy.sh
```

## Pré-requisitos

1. Stack do Marmitas já sobe a rede e os dados:

```bash
cd /opt/marmitas-catalog && docker compose up -d
```

2. Certificados no host:

```bash
ls /etc/letsencrypt/live/avera-marmitas.online/
ls /etc/letsencrypt/live/bangalostudio.com.br/
```

Sites **sem** certificado são ignorados no boot (o gateway sobe mesmo assim).

## Migrar do `marmitas-nginx` antigo

```bash
docker stop marmitas-nginx 2>/dev/null || true
docker rm marmitas-nginx 2>/dev/null || true

cd /opt/dsr-infra && ./deploy.sh

cd /opt/marmitas-catalog && docker compose up -d --remove-orphans
cd /opt/Bangalo-studio && ./deploy.sh
```

## Sites

| Arquivo | Domínio |
|---------|---------|
| `nginx/sites/marmitas.conf` | avera-marmitas.online |
| `nginx/sites/bangalo.conf` | bangalostudio.com.br |

A Bangalô mantém a fonte em `Bangalo-studio/nginx/site.conf`; o `deploy.sh` dela copia para `dsr-infra/nginx/sites/bangalo.conf` e recarrega o gateway.

## Novo domínio

1. DNS A → IP da VPS  
2. Certificado (`certbot certonly --standalone …` — pare o gateway se usar standalone)  
3. Crie `nginx/sites/novo.conf`  
4. Adicione `enable_site` em `scripts/entrypoint.sh`  
5. `./deploy.sh`

## Comandos úteis

```bash
./deploy.sh
docker compose logs -f gateway
docker compose exec gateway nginx -s reload
curl -s http://127.0.0.1/nginx-health
```
