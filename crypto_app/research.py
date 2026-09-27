import json
import sqlite3
from urllib.parse import urlsplit

from .strategy import DESCRIPTIONS, StrategySpec


def save_research(store: sqlite3.Connection, spec: StrategySpec) -> int:
    url = urlsplit(spec.source_url)
    if spec.kind not in DESCRIPTIONS or url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError("策略类型或来源链接无效")
    store.execute("CREATE TABLE IF NOT EXISTS research (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, parameters TEXT NOT NULL, version TEXT NOT NULL, source_url TEXT NOT NULL, note TEXT NOT NULL)")
    cursor = store.execute("INSERT INTO research(kind, parameters, version, source_url, note) VALUES (?,?,?,?,?)", (spec.kind, json.dumps(spec.parameters), spec.version, spec.source_url, spec.note))
    store.commit()
    return cursor.lastrowid


def load_research(store: sqlite3.Connection, record_id: int) -> StrategySpec:
    row = store.execute("SELECT kind, parameters, version, source_url, note FROM research WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise LookupError("研究记录不存在")
    return StrategySpec(row[0], json.loads(row[1]), row[2], row[3], row[4])
