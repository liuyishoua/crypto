import os
from pathlib import Path

from .app import create_app


if __name__ == "__main__":
    create_app(Path(os.environ.get("CRYPTO_RUNTIME_DIR", ".runtime"))).run(host="127.0.0.1", port=8765)
