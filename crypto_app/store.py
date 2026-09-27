import sqlite3
from pathlib import Path


def open_store(runtime_dir: Path) -> sqlite3.Connection:
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(runtime_dir / "crypto.db", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
