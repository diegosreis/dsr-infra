#!/usr/bin/env python3
"""Integração real do filtro gd-log-safe no gateway dsr-infra.

Usa nginx:alpine + template/entrypoint reais. Marcadores exclusivamente fictícios.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILTER_DIR = ROOT / "nginx/sites/gd-log-safe"
ENTRYPOINT = ROOT / "scripts/entrypoint.sh"
TEMPLATE = ROOT / "nginx/nginx.conf"
SITES = ROOT / "nginx/sites"
FILTER_PATH = "/etc/nginx/templates/sites/gd-log-safe/run.sh"

if not shutil.which("docker"):
    raise SystemExit("docker é obrigatório para este teste (nginx real)")

for path in (FILTER_DIR / "run.sh", FILTER_DIR / "redactor.awk", ENTRYPOINT, TEMPLATE):
    assert path.is_file(), path

subprocess.run(["sh", "-n", str(FILTER_DIR / "run.sh")], check=True)
subprocess.run(["sh", "-n", str(ENTRYPOINT)], check=True)

unit = subprocess.run(
    ["awk", "-f", str(FILTER_DIR / "redactor.awk")],
    input=(
        "ordinary warning without secrets\n"
        "connect() failed request: \"GET /convite/FICTIONAL_unit HTTP/1.1\"\n"
        "open() failed Referer: \"https://x/convite/FICTIONAL_unit?again=FICTIONAL_unit\"\n"
        "error /ordinary?token=FICTIONAL_unit\n"
    ),
    text=True,
    capture_output=True,
    check=True,
)
assert "FICTIONAL_unit" not in unit.stdout
assert "ordinary warning without secrets" in unit.stdout
assert unit.stdout.count("diagnostic context [redacted]") == 3

conf_text = TEMPLATE.read_text()
assert "error_log stderr warn;" in conf_text
http_preamble = conf_text.split("http {", 1)[1].split("server {", 1)[0]
active_http = "\n".join(
    line for line in http_preamble.splitlines() if line.strip() and not line.strip().startswith("#")
)
assert "access_log" not in active_http
compose = (ROOT / "docker-compose.yml").read_text()
assert "./nginx/sites:/etc/nginx/templates/sites" in compose
assert FILTER_PATH == "/etc/nginx/templates/sites/gd-log-safe/run.sh"


def docker_ip(container: str) -> str:
    out = subprocess.check_output(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ],
        text=True,
    ).strip()
    assert out, container
    return out


def curl_code(network: str, args: list[str]) -> int:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", network, "curlimages/curl:8.5.0", *args],
        text=True,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


with tempfile.TemporaryDirectory(prefix="dsr-gd-log-safe-") as tmp_raw:
    tmp = Path(tmp_raw)
    tmp.chmod(0o755)
    sites = tmp / "sites"
    shutil.copytree(SITES, sites)

    cert_root = tmp / "letsencrypt/live"
    base_cert_dir = cert_root / "gestaodental.online"
    base_cert_dir.mkdir(parents=True)
    cert = base_cert_dir / "fullchain.pem"
    key = base_cert_dir / "privkey.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=gestaodental.online",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for domain in (
        "avera-marmitas.online",
        "bangalostudio.com.br",
        "dentistamarciomaciel.com.br",
        "morenalab.site",
    ):
        d = cert_root / domain
        d.mkdir(parents=True)
        shutil.copy(cert, d / "fullchain.pem")
        shutil.copy(key, d / "privkey.pem")

    network = f"dsr-gd-net-{os.getpid()}"
    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    dead_name = f"dsr-gd-dead-{os.getpid()}"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                dead_name,
                "--network",
                network,
                "nginx:alpine",
                "sleep",
                "3600",
            ],
            check=True,
            capture_output=True,
        )

        (sites / "gestaodental.conf").write_text(
            f"""
server {{
    listen 80;
    server_name gestaodental.online;
    access_log off;
    error_log stderr warn;
    location / {{ return 301 https://$host$request_uri; }}
}}
server {{
    listen 443 ssl;
    http2 on;
    server_name gestaodental.online;
    ssl_certificate     /etc/letsencrypt/live/gestaodental.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gestaodental.online/privkey.pem;
    access_log off;
    error_log stderr warn;
    location ^~ /api/v1/public/patient-intake/ {{
        error_log stderr warn;
        set $up http://{dead_name}:9;
        proxy_pass $up;
        proxy_connect_timeout 1s;
        proxy_read_timeout 1s;
    }}
    location ^~ /convite/ {{
        error_log stderr warn;
        set $up http://{dead_name}:9;
        proxy_pass $up;
        proxy_connect_timeout 1s;
        proxy_read_timeout 1s;
    }}
    location /ordinary {{
        error_log stderr warn;
        set $up http://{dead_name}:9;
        proxy_pass $up;
        proxy_connect_timeout 1s;
        proxy_read_timeout 1s;
    }}
    location / {{
        return 200 "gd-fixture\\n";
        add_header Content-Type text/plain;
    }}
}}
"""
        )

        for name in ("bangalo", "maciel", "marmitas", "morenalab"):
            src = sites / f"{name}.conf"
            lines = []
            for line in src.read_text().splitlines():
                if "proxy_pass" in line:
                    lines.append("        return 204;")
                else:
                    lines.append(line)
            src.write_text("\n".join(lines) + "\n")

        def volumes_for(sites_dir: Path) -> list[str]:
            return [
                "-v",
                f"{TEMPLATE}:/etc/nginx/templates/nginx.conf:ro",
                "-v",
                f"{sites_dir}:/etc/nginx/templates/sites:ro",
                "-v",
                f"{ENTRYPOINT}:/gateway-entrypoint.sh:ro",
                "-v",
                f"{tmp / 'letsencrypt'}:/etc/letsencrypt:ro",
                "--network",
                network,
            ]

        sites_missing = tmp / "sites-missing"
        shutil.copytree(sites, sites_missing)
        shutil.rmtree(sites_missing / "gd-log-safe")
        missing = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                f"dsr-gd-missing-{os.getpid()}",
                *volumes_for(sites_missing),
                "--entrypoint",
                "/bin/sh",
                "nginx:alpine",
                "/gateway-entrypoint.sh",
            ],
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert missing.returncode != 0
        assert "gd-log-safe" in (missing.stdout + missing.stderr)

        syntax = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                f"dsr-gd-t-{os.getpid()}",
                *volumes_for(sites),
                "--entrypoint",
                "/bin/sh",
                "nginx:alpine",
                "-c",
                "mkdir -p /etc/nginx/sites-enabled /var/cache/nginx/images /var/www/certbot && "
                "cp /etc/nginx/templates/nginx.conf /etc/nginx/nginx.conf && "
                "rm -f /etc/nginx/sites-enabled/*.conf && "
                "for f in /etc/nginx/templates/sites/*.conf; do "
                "[ -f \"$f\" ] || continue; "
                "cp \"$f\" /etc/nginx/sites-enabled/; done && "
                f"/bin/sh {FILTER_PATH} nginx -e stderr -t",
            ],
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert syntax.returncode == 0, syntax.stdout + syntax.stderr

        marker = "GD_FAKE_" + os.urandom(12).hex()
        ref = f"https://gestaodental.online/convite/{marker}?repeat={marker}"
        gw_name = f"dsr-gd-run-{os.getpid()}"
        out_path = tmp / "gateway.out"
        err_path = tmp / "gateway.err"
        host = "gestaodental.online"

        with out_path.open("wb") as out_f, err_path.open("wb") as err_f:
            proc = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--name",
                    gw_name,
                    *volumes_for(sites),
                    "--entrypoint",
                    "/bin/sh",
                    "nginx:alpine",
                    "/gateway-entrypoint.sh",
                ],
                stdout=out_f,
                stderr=err_f,
            )
            try:
                for _ in range(100):
                    if proc.poll() is not None:
                        raise AssertionError(err_path.read_text() + out_path.read_text())
                    health = subprocess.run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--network",
                            network,
                            "curlimages/curl:8.5.0",
                            "-s",
                            "-o",
                            "/dev/null",
                            "-w",
                            "%{http_code}",
                            f"http://{gw_name}/nginx-health",
                        ],
                        text=True,
                        capture_output=True,
                        timeout=20,
                    )
                    if health.returncode == 0 and health.stdout.strip() == "200":
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("gateway não iniciou:\n" + err_path.read_text())

                gw_ip = docker_ip(gw_name)

                def status(path: str, referer: str) -> int:
                    return curl_code(
                        network,
                        [
                            "-sk",
                            "-o",
                            "/dev/null",
                            "-w",
                            "%{http_code}",
                            "-H",
                            f"Host: {host}",
                            "-H",
                            f"Referer: {referer}",
                            "--resolve",
                            f"{host}:443:{gw_ip}",
                            f"https://{host}{path}",
                        ],
                    )

                assert status(f"/convite/{marker}?repeat={marker}", ref) == 502
                assert status(f"/api/v1/public/patient-intake/{marker}?repeat={marker}", ref) == 502
                assert status("/ordinary", ref) == 502
                time.sleep(0.5)
            finally:
                subprocess.run(
                    ["docker", "kill", "--signal=QUIT", gw_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    subprocess.run(
                        ["docker", "rm", "-f", gw_name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    proc.wait(timeout=10)

        combined = out_path.read_text() + err_path.read_text()
        assert marker not in combined, "marcador bruto vazou nos logs do gateway"
        assert "diagnostic context [redacted]" in combined, "sem prova positiva de sanitização"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", dead_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "network", "rm", network],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

print(
    "OK: entrypoint+filtro (init, nginx -t, QUIT, filtro ausente); "
    "upstream 502 em convite/API/ordinary com Referer+query; "
    "marcador ausente; [redacted] presente; vhosts parseados"
)
