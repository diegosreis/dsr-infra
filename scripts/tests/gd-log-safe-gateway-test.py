#!/usr/bin/env python3
"""Integração real do filtro gd-log-safe no gateway dsr-infra.

Usa nginx:alpine + template/entrypoint/vhosts versionados. Marcadores fictícios.
"""
from __future__ import annotations

import os
import re
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
GD_SITE = SITES / "gestaodental.conf"
FILTER_PATH = "/etc/nginx/templates/sites/gd-log-safe/run.sh"
PID = os.getpid()
NETWORK = f"dsr-gd-net-{PID}"
CLEANUP: list[tuple[str, list[str]]] = []

if not shutil.which("docker"):
    raise SystemExit("docker é obrigatório para este teste (nginx real)")

for path in (
    FILTER_DIR / "run.sh",
    FILTER_DIR / "redactor.awk",
    ENTRYPOINT,
    TEMPLATE,
    GD_SITE,
):
    assert path.is_file(), path

assert "4142d65" in GD_SITE.read_text()
assert "gd_intake_safe" in GD_SITE.read_text()
assert "ortoimplante-web" in GD_SITE.read_text()
assert "access_log /dev/stdout gd_intake_safe" in GD_SITE.read_text()

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
    line
    for line in http_preamble.splitlines()
    if line.strip() and not line.strip().startswith("#")
)
assert "access_log" not in active_http
compose = (ROOT / "docker-compose.yml").read_text()
assert "./nginx/sites:/etc/nginx/templates/sites" in compose


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, **kwargs)


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


def track(kind: str, name: str) -> str:
    CLEANUP.append((kind, [name]))
    return name


def cleanup_all() -> None:
    for kind, names in reversed(CLEANUP):
        for name in names:
            if kind == "container":
                run(["docker", "rm", "-f", name])
            elif kind == "network":
                run(["docker", "network", "rm", name])
    CLEANUP.clear()


def volumes_for(sites_dir: Path, letsencrypt: Path) -> list[str]:
    return [
        "-v",
        f"{TEMPLATE}:/etc/nginx/templates/nginx.conf:ro",
        "-v",
        f"{sites_dir}:/etc/nginx/templates/sites:ro",
        "-v",
        f"{ENTRYPOINT}:/gateway-entrypoint.sh:ro",
        "-v",
        f"{letsencrypt}:/etc/letsencrypt:ro",
        "--network",
        NETWORK,
    ]


def start_ok_upstream(name: str) -> None:
    """Echo $request_uri on :80 and :3000 (aliases apontam para este container)."""
    conf = (
        "server { listen 80 default_server; listen 3000 default_server; "
        "location / { default_type text/plain; return 200 \"$request_uri\\n\"; } }\n"
    )
    track("container", name)
    r = run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            NETWORK,
            "--network-alias",
            "ortoimplante-web",
            "--network-alias",
            "ortoimplante-api",
            "--network-alias",
            "bangalo-app",
            "--network-alias",
            "marmitas-app",
            "--network-alias",
            "maciel-app",
            "--network-alias",
            "morenalab-app",
            "nginx:alpine",
            "sh",
            "-c",
            f"printf '%s' '{conf}' > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'",
        ],
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def start_fail_upstream(name: str) -> None:
    """Mesmos aliases, sem listener — força 502 no proxy."""
    track("container", name)
    r = run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            NETWORK,
            "--network-alias",
            "ortoimplante-web",
            "--network-alias",
            "ortoimplante-api",
            "--network-alias",
            "bangalo-app",
            "--network-alias",
            "marmitas-app",
            "--network-alias",
            "maciel-app",
            "--network-alias",
            "morenalab-app",
            "nginx:alpine",
            "sleep",
            "3600",
        ],
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


def curl_on_net(args: list[str], timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return run(
        ["docker", "run", "--rm", "--network", NETWORK, "curlimages/curl:8.5.0", *args],
        timeout=timeout,
    )


def assert_access_sanitized(logs: str, path_redacted: str, marker: str) -> None:
    assert marker not in logs, "marcador bruto no log"
    pattern = rf'"(GET|HEAD|POST) {re.escape(path_redacted)} HTTP/[0-9.]+" [0-9]{{3}} .*rt='
    assert re.search(pattern, logs), f"access sanitizado ausente para {path_redacted}"


def quit_gateway(proc: subprocess.Popen[bytes], name: str, timeout: float = 20.0) -> int:
    kill = run(["docker", "kill", "--signal=QUIT", name])
    assert kill.returncode == 0, f"QUIT não enviado: {kill.stderr}"
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"QUIT não encerrou em {timeout}s") from exc


try:
    run(["docker", "network", "create", NETWORK], check=True, timeout=30)
    track("network", NETWORK)

    with tempfile.TemporaryDirectory(prefix="dsr-gd-log-safe-") as tmp_raw:
        tmp = Path(tmp_raw)
        tmp.chmod(0o755)
        sites = tmp / "sites"
        shutil.copytree(SITES, sites)
        # Vhosts reais intactos (sem trocar proxy_pass / inventar server).
        assert (sites / "gestaodental.conf").read_bytes() == GD_SITE.read_bytes()
        for name in ("bangalo", "maciel", "marmitas", "morenalab"):
            assert "proxy_pass" in (sites / f"{name}.conf").read_text()

        cert_root = tmp / "letsencrypt/live"
        domains = (
            "gestaodental.online",
            "avera-marmitas.online",
            "bangalostudio.com.br",
            "dentistamarciomaciel.com.br",
            "morenalab.site",
        )
        first = cert_root / domains[0]
        first.mkdir(parents=True)
        cert, key = first / "fullchain.pem", first / "privkey.pem"
        run(
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
            timeout=30,
        )
        for domain in domains[1:]:
            d = cert_root / domain
            d.mkdir(parents=True)
            shutil.copy(cert, d / "fullchain.pem")
            shutil.copy(key, d / "privkey.pem")

        # --- filtro ausente ---
        sites_missing = tmp / "sites-missing"
        shutil.copytree(sites, sites_missing)
        shutil.rmtree(sites_missing / "gd-log-safe")
        missing = run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                f"dsr-gd-missing-{PID}",
                *volumes_for(sites_missing, tmp / "letsencrypt"),
                "--entrypoint",
                "/bin/sh",
                "nginx:alpine",
                "/gateway-entrypoint.sh",
            ],
            timeout=60,
        )
        assert missing.returncode != 0
        assert "gd-log-safe" in (missing.stdout + missing.stderr)

        # --- nginx -t com vhosts reais ---
        syntax = run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                f"dsr-gd-t-{PID}",
                *volumes_for(sites, tmp / "letsencrypt"),
                "--entrypoint",
                "/bin/sh",
                "nginx:alpine",
                "-c",
                "mkdir -p /etc/nginx/sites-enabled /var/cache/nginx/images /var/www/certbot && "
                "cp /etc/nginx/templates/nginx.conf /etc/nginx/nginx.conf && "
                "rm -f /etc/nginx/sites-enabled/*.conf && "
                "for f in /etc/nginx/templates/sites/*.conf; do "
                "[ -f \"$f\" ] || continue; cp \"$f\" /etc/nginx/sites-enabled/; done && "
                f"/bin/sh {FILTER_PATH} nginx -e stderr -t",
            ],
            timeout=60,
        )
        assert syntax.returncode == 0, syntax.stdout + syntax.stderr

        marker = "GD_FAKE_" + os.urandom(12).hex()
        ref = f"https://gestaodental.online/convite/{marker}?repeat={marker}"
        host = "gestaodental.online"
        convite_path = f"/convite/{marker}?repeat={marker}"
        api_path = f"/api/v1/public/patient-intake/{marker}?repeat={marker}"
        ordinary_path = f"/ordinary-probe?repeat={marker}"

        def run_gateway(
            phase: str, upstream_starter, expected_status: int
        ) -> tuple[str, str, int]:
            up_name = f"dsr-gd-up-{phase}-{PID}"
            gw_name = f"dsr-gd-gw-{phase}-{PID}"
            upstream_starter(up_name)
            time.sleep(0.4)
            out_path = tmp / f"{phase}.out"
            err_path = tmp / f"{phase}.err"
            track("container", gw_name)
            with out_path.open("wb") as out_f, err_path.open("wb") as err_f:
                proc = subprocess.Popen(
                    [
                        "docker",
                        "run",
                        "--name",
                        gw_name,
                        *volumes_for(sites, tmp / "letsencrypt"),
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
                        health = curl_on_net(
                            [
                                "-s",
                                "-o",
                                "/dev/null",
                                "-w",
                                "%{http_code}",
                                f"http://{gw_name}/nginx-health",
                            ],
                            timeout=20,
                        )
                        if health.returncode == 0 and health.stdout.strip() == "200":
                            break
                        time.sleep(0.1)
                    else:
                        raise AssertionError("gateway não iniciou:\n" + err_path.read_text())

                    gw_ip = docker_ip(gw_name)

                    def hit(path: str) -> tuple[int, str]:
                        r = curl_on_net(
                            [
                                "-sk",
                                "-D",
                                "-",
                                "-o",
                                "-",
                                "-w",
                                "\n__CODE__%{http_code}",
                                "-H",
                                f"Host: {host}",
                                "-H",
                                f"Referer: {ref}",
                                "--resolve",
                                f"{host}:443:{gw_ip}",
                                f"https://{host}{path}",
                            ],
                            timeout=45,
                        )
                        assert r.returncode == 0, r.stderr
                        body, _, code_s = r.stdout.rpartition("__CODE__")
                        return int(code_s.strip()), body

                    code_c, body_c = hit(convite_path)
                    code_a, body_a = hit(api_path)
                    code_o, _ = hit(ordinary_path)
                    for route, code in (
                        ("convite", code_c),
                        ("api", code_a),
                        ("ordinary", code_o),
                    ):
                        assert code == expected_status, (
                            f"fase={phase} rota={route}: esperado HTTP "
                            f"{expected_status}, recebido {code}"
                        )
                    time.sleep(0.5)
                    rc = quit_gateway(proc, gw_name)
                    assert out_path.exists() and err_path.exists()
                    return out_path.read_text() + err_path.read_text(), body_c + "\n" + body_a, rc
                except Exception:
                    run(["docker", "rm", "-f", gw_name])
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait(timeout=10)
                    raise

        # Fase OK: URI intacta + access log sanitizado
        logs_ok, bodies, rc_ok = run_gateway("ok", start_ok_upstream, 200)
        assert rc_ok == 0, f"QUIT fase ok rc={rc_ok}"
        assert marker not in logs_ok
        assert_access_sanitized(logs_ok, "/convite/[redacted]", marker)
        assert_access_sanitized(logs_ok, "/api/v1/public/patient-intake/[redacted]", marker)
        assert re.search(
            r'"GET /ordinary-probe HTTP/[0-9.]+" [0-9]{3} .*rt=',
            logs_ok,
        ), "access da rota comum ausente"
        assert convite_path in bodies, "URI /convite ao upstream foi alterada"
        assert api_path in bodies, "URI /api patient-intake ao upstream foi alterada"

        run(["docker", "rm", "-f", f"dsr-gd-up-ok-{PID}"])

        # Fase FAIL: error_log com Referer/query sensíveis
        logs_fail, _, rc_fail = run_gateway("fail", start_fail_upstream, 502)
        assert rc_fail == 0, f"QUIT fase fail rc={rc_fail}"
        assert marker not in logs_fail
        assert "diagnostic context [redacted]" in logs_fail
        assert_access_sanitized(logs_fail, "/convite/[redacted]", marker)
        assert_access_sanitized(logs_fail, "/api/v1/public/patient-intake/[redacted]", marker)

finally:
    cleanup_all()

print(
    "OK: vhosts reais + entrypoint; filtro ausente; nginx -t; "
    "access sanitizado (método/status/rt); URI upstream intacta; "
    "error [redacted]; QUIT com encerramento assertado"
)
