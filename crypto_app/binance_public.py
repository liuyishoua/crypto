import csv
import io
import json
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
        matches = [row for row in self._symbols if query in row.symbol or query in row.base]
        if matches:
            selected = matches[:20]
            try:
                response = self.session.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbols": json.dumps([row.symbol for row in selected])}, timeout=10)
                response.raise_for_status()
                volumes = {item["symbol"]: Decimal(str(item["quoteVolume"])) for item in response.json()}
                matches = [row._replace(quote_volume=volumes.get(row.symbol)) for row in matches]
            except Exception:
                pass
        return matches

    def candles(self, symbol: str, interval: str, start: datetime, end: datetime) -> MarketData:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("日期范围无效")
        bars = []
        sources = set()
        cursor = start
        now = datetime.now(timezone.utc)
        while cursor < end:
            next_month = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1, tzinfo=timezone.utc)
            segment_end = min(next_month, end)
            full_old_month = cursor.day == 1 and cursor.hour == cursor.minute == cursor.second == cursor.microsecond == 0 and segment_end == next_month and next_month < datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            if full_old_month:
                try:
                    archive = self.archive_month(symbol, interval, cursor.year, cursor.month)
                    bars.extend(bar for bar in archive.candles if cursor <= bar.open_at < segment_end)
                    sources.add("binance-public-data")
                    cursor = segment_end
                    continue
                except MarketUnavailable:
                    pass
            bars.extend(self._rest_candles(symbol, interval, cursor, segment_end))
            sources.add("binance-rest")
            cursor = segment_end
        candles = tuple(bars)
        source = next(iter(sources)) if len(sources) == 1 else "binance-public-data+rest"
        result = MarketData("binance", "spot", symbol, interval, candles, source, datetime.now(timezone.utc), checksum_candles(candles))
        validate_candles(result)
        return result

    def _rest_candles(self, symbol, interval, start, end):
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
        return bars

    def archive_day(self, symbol: str, interval: str, day) -> MarketData:
        return self._archive(symbol, interval, day.isoformat(), "daily")

    def archive_month(self, symbol: str, interval: str, year: int, month: int) -> MarketData:
        return self._archive(symbol, interval, f"{year:04d}-{month:02d}", "monthly")

    def _archive(self, symbol: str, interval: str, period: str, grouping: str) -> MarketData:
        name = f"{symbol}-{interval}-{period}"
        url = f"https://data.binance.vision/data/spot/{grouping}/klines/{symbol}/{interval}/{name}.zip"
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            with ZipFile(io.BytesIO(response.content)) as zipped:
                with zipped.open(f"{name}.csv") as stream:
                    rows = list(csv.reader(io.TextIOWrapper(stream)))
        except Exception as exc:
            raise MarketUnavailable(f"历史归档不可用: {exc}") from exc
        bars = tuple(Candle(datetime.fromtimestamp(int(row[0]) / (1_000_000 if int(row[0]) >= 10**15 else 1000), timezone.utc), *(Decimal(row[i]) for i in (1, 2, 3, 4, 5))) for row in rows)
        result = MarketData("binance", "spot", symbol, interval, bars, "binance-public-data", datetime.now(timezone.utc), checksum_candles(bars))
        validate_candles(result, min_bars=1)
        return result
