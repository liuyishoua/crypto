import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import NamedTuple
from zipfile import ZipFile

import requests

from .market import Candle, MarketData, checksum_candles, validate_candles


class MarketUnavailable(Exception):
    def __init__(self, message: str, cached_at=None):
        super().__init__(message)
        self.cached_at = cached_at


class SymbolInfo(NamedTuple):
    symbol: str
    base: str
    quote: str
    status: str
    quote_volume: Decimal | None


class BinancePublicClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self._symbols = []
        self._symbols_at = None

    def symbols(self, query: str) -> list[SymbolInfo]:
        try:
            response = self.session.get("https://api.binance.com/api/v3/exchangeInfo", timeout=10)
            response.raise_for_status()
            self._symbols = [SymbolInfo(row["symbol"], row["baseAsset"], row["quoteAsset"], row["status"], None) for row in response.json()["symbols"] if row.get("isSpotTradingAllowed")]
            self._symbols_at = datetime.now(timezone.utc)
        except Exception as exc:
            raise MarketUnavailable(f"交易对目录不可用: {exc}", cached_at=self._symbols_at) from exc
        query = query.upper().strip()
        return [row for row in self._symbols if query in row.symbol or query in row.base]

    def candles(self, symbol: str, interval: str, start: datetime, end: datetime) -> MarketData:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("日期范围无效")
        bars = []
        cursor = int(start.timestamp() * 1000)
        finish = int(end.timestamp() * 1000)
        while cursor < finish:
            try:
                response = self.session.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": finish - 1, "limit": 1000}, timeout=15)
                response.raise_for_status()
                batch = response.json()
            except Exception as exc:
                raise MarketUnavailable(f"K 线不可用: {exc}") from exc
            if not batch:
                break
            bars.extend(Candle(datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc), *(Decimal(str(row[i])) for i in (1, 2, 3, 4, 5))) for row in batch)
            next_cursor = int(batch[-1][0]) + 1
            if next_cursor <= cursor:
                raise ValueError("币安 K 线分页未前进")
            cursor = next_cursor
        candles = tuple(bars)
        result = MarketData("binance", "spot", symbol, interval, candles, "binance-rest", datetime.now(timezone.utc), checksum_candles(candles))
        validate_candles(result)
        return result

    def archive_day(self, symbol: str, interval: str, day) -> MarketData:
        name = f"{symbol}-{interval}-{day.isoformat()}"
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}/{name}.zip"
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            with ZipFile(io.BytesIO(response.content)) as zipped:
                with zipped.open(f"{name}.csv") as stream:
                    rows = list(csv.reader(io.TextIOWrapper(stream)))
        except Exception as exc:
            raise MarketUnavailable(f"历史归档不可用: {exc}") from exc
        bars = tuple(Candle(datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc), *(Decimal(row[i]) for i in (1, 2, 3, 4, 5))) for row in rows)
        result = MarketData("binance", "spot", symbol, interval, bars, "binance-public-data", datetime.now(timezone.utc), checksum_candles(bars))
        validate_candles(result, min_bars=1)
        return result
