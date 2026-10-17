from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE_PACKAGE = "@modelcontextprotocol/conformance@0.2.0-alpha.10"
PROTOCOL_VERSION = "2026-07-28"
SCENARIOS = (
    "server-stateless",
    "tools-list",
    "dns-rebinding-protection",
)


def main() -> int:
    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("npx is required for the official MCP conformance smoke.")

    host = "127.0.0.1"
    port = _unused_port(host)
    url = f"http://{host}:{port}/mcp"
    with tempfile.TemporaryDirectory(prefix="django-veo-admin-api-mcp-conformance-") as tmp:
        log_path = Path(tmp) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "scripts.mcp_conformance_server:app",
                    "--host",
                    host,
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                _wait_for_server(server, host, port, log_path)
                for scenario in SCENARIOS:
                    subprocess.run(
                        [
                            npx,
                            "--yes",
                            CONFORMANCE_PACKAGE,
                            "server",
                            "--url",
                            url,
                            "--scenario",
                            scenario,
                            "--spec-version",
                            PROTOCOL_VERSION,
                        ],
                        cwd=tmp,
                        check=True,
                        timeout=180,
                    )
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)

    print(f"MCP {PROTOCOL_VERSION} transport conformance smoke passed: {', '.join(SCENARIOS)}.")
    return 0


def _unused_port(host: str) -> int:
    with socket.socket() as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def _wait_for_server(server, host: str, port: int, log_path: Path) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"MCP conformance server exited early:\n{log_path.read_text(encoding='utf-8')}")
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"MCP conformance server did not start:\n{log_path.read_text(encoding='utf-8')}")


if __name__ == "__main__":
    raise SystemExit(main())
