# dsr-infra

Infraestrutura compartilhada da VPS (Diego Reis):

- **MySQL**, **MinIO**, **Redis**
- **Gateway Nginx** (portas 80/443)

As apps **não** sobem banco/storage — só entram na rede `dsr-shared`.

## Arquitetura

```text
Internet
   │
vps-gateway (:80/:443)
   ├─ avera-marmitas.online  → marmitas-app:3000
   └─ bangalostudio.com.br   → bangalo-app:3000
              │
         dsr-shared
    ┌─────┼──────┐
 dsr-mysql  dsr-minio  dsr-redis
    │
 apps (repos separados)
```

| Repo | Papel |
|------|--------|
| **dsr-infra** | Dados + gateway |
| [marmitas-catalog](https://github.com/diegosreis/marmitas-catalog) | App Marmitas |
| [Bangalo-studio](https://github.com/diegosreis/Bangalo-studio) | App Bangalô |

DNS interno (aliases na rede): `mysql`, `minio`, `redis`.

## Setup inicial na VPS

```bash
cd /opt
git clone https://github.com/diegosreis/dsr-infra.git
cd dsr-infra
cp .env.example .env
nano .env   # senhas iguais às que já usa no Marmitas

chmod +x deploy.sh scripts/entrypoint.sh
./deploy.sh
```

Volumes reutilizam os nomes antigos (sem perder dados):

- `marmitas-catalog_mysql_data`
- `marmitas-catalog_minio_data`
- `marmitas-catalog_redis_data`

## Migrar da stack antiga (marmitas com mysql/nginx embutidos)

```bash
# 1. Parar apps e serviços antigos (NÃO use -v — preserva volumes)
cd /opt/marmitas-catalog
docker compose stop
docker stop marmitas-nginx marmitas-mysql marmitas-minio marmitas-redis 2>/dev/null || true
docker rm marmitas-nginx marmitas-mysql marmitas-minio marmitas-redis marmitas-minio-init 2>/dev/null || true

# 2. Subir infra nova (mesmos volumes)
cd /opt/dsr-infra
# .env com as MESMAS senhas do .env antigo do marmitas
./deploy.sh

# 3. Apps na rede dsr-shared
cd /opt/marmitas-catalog && git pull && docker compose up -d --remove-orphans
cd /opt/Bangalo-studio && git pull && ./deploy.sh

# 4. Testar
curl -s https://avera-marmitas.online | grep -o '<title>[^<]*</title>'
curl -s https://bangalostudio.com.br | grep -o '<title>[^<]*</title>'
```

## Certificados

```bash
ls /etc/letsencrypt/live/avera-marmitas.online/
ls /etc/letsencrypt/live/bangalostudio.com.br/
```

Sites sem certificado são ignorados no boot do gateway.

## Novo app na rede

No `docker-compose.yml` da app:

```yaml
networks:
  shared-infra:
    external: true
    name: dsr-shared
```

Hostnames: `mysql:3306`, `minio:9000`, `redis:6379`.

## Sites Nginx

| Arquivo | Domínio |
|---------|---------|
| `nginx/sites/marmitas.conf` | avera-marmitas.online |
| `nginx/sites/bangalo.conf` | bangalostudio.com.br |

Bangalô: fonte em `Bangalo-studio/nginx/site.conf` → copiada no deploy para `nginx/sites/bangalo.conf`.
