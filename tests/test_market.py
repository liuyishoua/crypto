from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest

from crypto_app.market import Candle, MarketData, checksum_candles, import_csv, load_market_cache, save_market_cache, validate_candles
from crypto_app.binance_public import BinancePublicClient, MarketUnavailable
from crypto_app.store import open_store


UTC = timezone.utc


def fixture_data(count=100):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    candles = tuple(
        Candle(start + timedelta(days=i), Decimal("10"), Decimal("12"), Decimal("9"), Decimal("11"), Decimal("100"))
        for i in range(count)
    )
    return MarketData("binance", "spot", "SOLUSDT", "1d", candles, "fixture", start, checksum_candles(candles))


@pytest.mark.parametrize("change", ["gap", "duplicate", "reverse", "bad_price"])
def test_rejects_broken_history(change):
    data = fixture_data()
    bars = list(data.candles)
    if change == "gap":
        bars[50] = Candle(bars[50].open_at + timedelta(days=1), *bars[50].prices())
    elif change == "duplicate":
        bars[50] = Candle(bars[49].open_at, *bars[50].prices())
    elif change == "reverse":
        bars[50], bars[51] = bars[51], bars[50]
    else:
        bars[50] = Candle(bars[50].open_at, Decimal("0"), Decimal("12"), Decimal("9"), Decimal("11"), Decimal("100"))
    with pytest.raises(ValueError):
        validate_candles(data._replace(candles=tuple(bars)))


def test_rejects_short_history_and_missing_csv_metadata():
    with pytest.raises(ValueError, match="100"):
        validate_candles(fixture_data(99))
    with pytest.raises(ValueError):
        import_csv("open_at,open,high,low,close,volume\n", symbol="SOLUSDT", interval="1d", timezone_name="")


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.fail = False
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if self.fail:
            raise OSError("offline")
        if url.endswith("exchangeInfo"):
            return Response({"symbols": [
                {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
                {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
                {"symbol": "DOGEBTC", "baseAsset": "DOGE", "quoteAsset": "BTC", "status": "TRADING", "isSpotTradingAllowed": True},
            ]})
        if url.endswith("ticker/24hr"):
            return Response([{"symbol": "BTCUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}, {"symbol": "SOLUSDT", "quoteVolume": "123456.78", "priceChangePercent": "-2.5"}])
        return Response([])


def test_browses_active_usdt_pairs_by_volume_and_keeps_stale_catalog():
    session = Session()
    client = BinancePublicClient(session=session)
    assert [item.symbol for item in client.symbols("")] == ["SOLUSDT", "BTCUSDT"]
    assert [item.symbol for item in client.symbols("sol")] == ["SOLUSDT"]
    assert client.symbols("sol")[0].quote_volume == Decimal("123456.78")
    assert client.symbols("sol")[0].change_percent == Decimal("-2.5")
    assert all(url.startswith("https://data-api.binance.vision/") for url in session.urls)
    assert len(session.urls) == 2
    session.fail = True
    client._symbols_at = datetime(2020, 1, 1, tzinfo=UTC)
    assert client.symbols("sol")[0].symbol == "SOLUSDT"
    assert client.catalog_stale is True
    assert [item.symbol for item in client.symbols("doge", quote="BTC")] == ["DOGEBTC"]


def test_catalog_error_without_cache_is_explicit():
    session = Session()
    session.fail = True
    with pytest.raises(MarketUnavailable, match="交易对目录不可用"):
        BinancePublicClient(session=session).symbols("")


def test_search_prioritizes_exact_base_over_volume():
    class SearchSession(Session):
        def get(self, url, **kwargs):
            if url.endswith("exchangeInfo"):
                return Response({"symbols": [
                    {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
                    {"symbol": "RESOLVUSDT", "baseAsset": "RESOLV", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True},
                ]})
            if url.endswith("ticker/24hr"):
                return Response([
                    {"symbol": "SOLUSDT", "quoteVolume": "100", "priceChangePercent": "1"},
                    {"symbol": "RESOLVUSDT", "quoteVolume": "100000", "priceChangePercent": "2"},
                ])
            return super().get(url, **kwargs)

    assert [item.symbol for item in BinancePublicClient(session=SearchSession()).symbols("sol")][:2] == ["SOLUSDT", "RESOLVUSDT"]


def test_market_cache_keeps_identity_and_source(tmp_path):
    store = open_store(tmp_path)
    data = fixture_data()
    save_market_cache(store, data)
    loaded = load_market_cache(store, "binance", "spot", "SOLUSDT", "1d", data.candles[0].open_at, data.candles[-1].open_at)
    assert loaded == data
    assert load_market_cache(store, "binance", "spot", "BTCUSDT", "1d", data.candles[0].open_at, data.candles[-1].open_at) is None


def test_market_cache_rejects_tampered_candles(tmp_path):
    store = open_store(tmp_path)
    data = fixture_data()
    save_market_cache(store, data)
    store.execute("UPDATE market_cache SET payload=REPLACE(payload, '100', '101')")
    store.commit()
    with pytest.raises(ValueError, match="校验"):
        load_market_cache(store, "binance", "spot", "SOLUSDT", "1d", data.candles[0].open_at, data.candles[-1].open_at)


def test_public_archive_day_parses_binance_csv():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("SOLUSDT-1d-2024-01-01.csv", "1704067200000,10,12,9,11,100,1704153599999,0,0,0,0,0\n")

    class ArchiveSession:
        def get(self, url, **kwargs):
            response = Response(None)
            response.content = buffer.getvalue()
            return response

    data = BinancePublicClient(session=ArchiveSession()).archive_day("SOLUSDT", "1d", datetime(2024, 1, 1, tzinfo=UTC).date())
    assert len(data.candles) == 1
    assert data.candles[0].open == Decimal("10")
    assert data.source == "binance-public-data"


def test_public_archive_uses_microsecond_timestamps_after_2025():
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("SOLUSDT-1d-2025-01-01.csv", "1735689600000000,10,12,9,11,100,1735775999999999,0,0,0,0,0\n")

    class ArchiveSession:
        def get(self, url, **kwargs):
            response = Response(None)
            response.content = buffer.getvalue()
            return response

    data = BinancePublicClient(session=ArchiveSession()).archive_day("SOLUSDT", "1d", datetime(2025, 1, 1, tzinfo=UTC).date())
    assert data.candles[0].open_at == datetime(2025, 1, 1, tzinfo=UTC)


def test_full_historical_month_uses_archive():
    class ArchiveClient(BinancePublicClient):
        def archive_month(self, symbol, interval, year, month):
            assert (symbol, interval, year, month) == ("SOLUSDT", "1h", 2024, 2)
            start = datetime(2024, 2, 1, tzinfo=UTC)
            bars = tuple(Candle(start + timedelta(hours=i), Decimal(10), Decimal(12), Decimal(9), Decimal(11), Decimal(100)) for i in range(29 * 24))
            return MarketData("binance", "spot", symbol, interval, bars, "binance-public-data", start, checksum_candles(bars))

    class NoRest:
        def get(self, *_args, **_kwargs): raise AssertionError("monthly history should use archive")

    data = ArchiveClient(session=NoRest()).candles("SOLUSDT", "1h", datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC))
    assert data.source == "binance-public-data"
    assert len(data.candles) == 29 * 24
