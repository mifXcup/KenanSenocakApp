from __future__ import annotations

import argparse
import os

import uvicorn

from ks_yonetim.main import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kenan Şenocak Yönetim yerel veri hizmeti")
    parser.add_argument("--host", default=os.getenv("KS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("KS_PORT", "8765")))
    return parser.parse_args()


def validate_runtime(host: str, port: int) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Güvenlik nedeniyle sidecar yalnızca loopback adresinde çalışabilir.")
    if not 1 <= port <= 65535:
        raise SystemExit("Port 1 ile 65535 arasında olmalıdır.")
    token = os.getenv("KS_SIDECAR_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("KS_SIDECAR_TOKEN en az 32 karakter olmalıdır.")


def main() -> None:
    args = parse_args()
    validate_runtime(args.host, args.port)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        access_log=False,
        server_header=False,
        date_header=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
