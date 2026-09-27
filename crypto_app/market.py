import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import NamedTuple


INTERVALS = {"1m": timedelta(minutes=1), "5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}


class Candle(NamedTuple):
    open_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def prices(self):
        return self.open, self.high, self.low, self.close, self.volume


class MarketData(NamedTuple):
    exchange: str
    market_type: str
    symbol: str
    interval: str
    candles: tuple[Candle, ...]
    source: str
    fetched_at: datetime
    checksum: str


def validate_candles(data: MarketData, min_bars: int = 100) -> None:
    if data.interval not in INTERVALS:
        raise ValueError("不支持的 K 线周期")
    if len(data.candles) < min_bars:
        raise ValueError(f"至少需要 {min_bars} 根连续 K 线")
    previous = None
    for bar in data.candles:
        if bar.open_at.tzinfo is None or bar.open_at.utcoffset() != timedelta(0):
            raise ValueError("K 线时间必须为 UTC")
        if previous is not None and bar.open_at - previous != INTERVALS[data.interval]:
            raise ValueError("K 线缺失、重复或逆序")
        if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
            raise ValueError("K 线价格或成交量异常")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
            raise ValueError("K 线 OHLC 不一致")
        previous = bar.open_at


def checksum_candles(candles: tuple[Candle, ...]) -> str:
    body = "\n".join(",".join((bar.open_at.isoformat(), *(str(value) for value in bar.prices()))) for bar in candles)
    return hashlib.sha256(body.encode()).hexdigest()


def import_csv(body: str, *, symbol: str, interval: str, timezone_name: str, columns=None) -> MarketData:
    if timezone_name != "UTC" or not symbol or not interval:
        raise ValueError("必须指定交易对、周期和 UTC 时区")
    fieldnames = columns or {key: key for key in ("open_at", "open", "high", "low", "close", "volume")}
    rows = csv.DictReader(io.StringIO(body))
    if not rows.fieldnames or not all(value in rows.fieldnames for value in fieldnames.values()):
        raise ValueError("CSV 缺少所需字段")
    bars = tuple(Candle(datetime.fromisoformat(row[fieldnames["open_at"]].replace("Z", "+00:00")), *(Decimal(row[fieldnames[key]]) for key in ("open", "high", "low", "close", "volume"))) for row in rows)
    result = MarketData("csv", "spot", symbol.upper(), interval, bars, "csv-import", datetime.now(timezone.utc), checksum_candles(bars))
    validate_candles(result)
    return result


def save_market_cache(store: sqlite3.Connection, data: MarketData) -> None:
    validate_candles(data, min_bars=1)
    store.execute("CREATE TABLE IF NOT EXISTS market_cache (exchange TEXT, market_type TEXT, symbol TEXT, interval TEXT, start_at TEXT, end_at TEXT, payload TEXT, PRIMARY KEY(exchange,market_type,symbol,interval,start_at,end_at))")
    payload = {"source": data.source, "fetched_at": data.fetched_at.isoformat(), "checksum": data.checksum, "candles": [[bar.open_at.isoformat(), *(str(v) for v in bar.prices())] for bar in data.candles]}
    store.execute("INSERT OR REPLACE INTO market_cache VALUES (?,?,?,?,?,?,?)", (data.exchange, data.market_type, data.symbol, data.interval, data.candles[0].open_at.isoformat(), data.candles[-1].open_at.isoformat(), json.dumps(payload)))
    store.commit()


def load_market_cache(store: sqlite3.Connection, exchange: str, market_type: str, symbol: str, interval: str, start: datetime, end: datetime) -> MarketData | None:
    store.execute("CREATE TABLE IF NOT EXISTS market_cache (exchange TEXT, market_type TEXT, symbol TEXT, interval TEXT, start_at TEXT, end_at TEXT, payload TEXT, PRIMARY KEY(exchange,market_type,symbol,interval,start_at,end_at))")
    row = store.execute("SELECT payload FROM market_cache WHERE exchange=? AND market_type=? AND symbol=? AND interval=? AND start_at=? AND end_at=?", (exchange, market_type, symbol, interval, start.isoformat(), end.isoformat())).fetchone()
    if row is None:
        return None
    payload = json.loads(row[0])
    bars = tuple(Candle(datetime.fromisoformat(record[0]), *(Decimal(value) for value in record[1:])) for record in payload["candles"])
    data = MarketData(exchange, market_type, symbol, interval, bars, payload["source"], datetime.fromisoformat(payload["fetched_at"]), payload["checksum"])
    if checksum_candles(bars) != data.checksum:
        raise ValueError("缓存校验失败")
    return data
