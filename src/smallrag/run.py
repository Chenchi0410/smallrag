from pathlib import Path

import uvicorn

from smallrag.config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.https_certfile or not settings.https_keyfile:
        raise SystemExit("HTTPS_CERTFILE and HTTPS_KEYFILE are required to start SmallRAG")

    certfile = Path(settings.https_certfile)
    keyfile = Path(settings.https_keyfile)
    if not certfile.is_file() or not keyfile.is_file():
        raise SystemExit("HTTPS certificate or private-key file does not exist")

    uvicorn.run(
        "smallrag.main:app",
        host=settings.server_host,
        port=settings.server_port,
        ssl_certfile=str(certfile),
        ssl_keyfile=str(keyfile),
    )


if __name__ == "__main__":
    main()
