from datetime import datetime, timedelta, timezone
from decimal import Decimal

from crypto_app.app import create_app
from crypto_app.binance_public import SymbolInfo
from crypto_app.binance_public import MarketUnavailable
from crypto_app.market import Candle, MarketData, checksum_candles


class MarketClient:
    catalog_stale = False

    def symbols(self, query, quote="USDT"):
        items = [SymbolInfo("BTCUSDT", "BTC", "USDT", "TRADING", Decimal("1000"), Decimal("2.5")), SymbolInfo("SOLUSDT", "SOL", "USDT", "TRADING", Decimal("200"), Decimal("-1.5"))]
        return [item for item in items if query.upper() in item.symbol and (not quote or item.quote == quote)]

    def candles(self, symbol, interval, start, end):
        bars = tuple(Candle(datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100)) for i in range(105))
        return MarketData("binance", "spot", symbol, interval, bars, "fixture", datetime(2024, 5, 1, tzinfo=timezone.utc), checksum_candles(bars))


def client(tmp_path):
    app = create_app(tmp_path, market_client=MarketClient())
    app.testing = True
    browser = app.test_client()
    browser.get("/health")
    csrf = browser.get_cookie("csrf_token").value
    return browser, {"Host": "localhost", "Origin": "http://localhost", "X-App-Request": "1", "X-CSRF-Token": csrf}


def test_search_candles_research_and_backtest(tmp_path):
    browser, headers = client(tmp_path)
    listing = browser.get("/api/symbols?q=SOL&quote=USDT").json
    assert [item["symbol"] for item in listing["items"]] == ["SOLUSDT"]
    assert listing["items"][0]["change_percent"] == "-1.5"
    assert listing["stale"] is False
    candles = browser.get("/api/candles?symbol=SOLUSDT&interval=1d&start=2024-01-01&end=2024-04-15")
    assert candles.status_code == 200
    assert len(candles.json["candles"]) == 105
    assert candles.json["source"] == "fixture"
    assert len(candles.json["insights"]) == 105
    assert candles.json["insights"][20]["momentum_20"] == 0.0
    research = browser.post("/api/research", headers=headers, json={"kind": "buy_hold", "parameters": {}, "version": "1", "source_url": "https://example.com", "note": "学习记录"})
    assert research.status_code == 201
    result = browser.post("/api/backtests", headers=headers, json={"symbol": "SOLUSDT", "interval": "1d", "start": "2024-01-01", "end": "2024-04-15", "kind": "buy_hold", "parameters": {}, "initial_cash": "1000", "fee_rate": "0.001", "slippage_rate": "0.002"})
    assert result.status_code == 201
    saved = browser.get(f"/api/backtests/{result.json['id']}")
    assert saved.json["symbol"] == "SOLUSDT"
    assert saved.json["fills"][0]["side"] == "BUY"
    listing = browser.get("/api/backtests")
    assert listing.json["items"][0]["id"] == result.json["id"]


def test_invalid_market_input_is_explained(tmp_path):
    browser, headers = client(tmp_path)
    response = browser.get("/api/candles?symbol=BAD!&interval=1d&start=x&end=y")
    assert response.status_code == 400
    assert "error" in response.json
    offset = browser.get("/api/candles?symbol=SOLUSDT&interval=1d&start=2024-01-01T08:00%2B08:00&end=2024-04-15")
    assert offset.status_code == 400
    assert "日期必须" in offset.json["error"]
    oversized = browser.get("/api/candles?symbol=SOLUSDT&interval=15m&start=2024-01-01&end=2024-06-01")
    assert oversized.status_code == 400
    assert "3000" in oversized.json["error"]


def test_rejects_incomplete_requested_history(tmp_path):
    browser, headers = client(tmp_path)
    result = browser.post("/api/backtests", headers=headers, json={"symbol": "SOLUSDT", "interval": "1d", "start": "2024-01-01", "end": "2024-04-20", "kind": "buy_hold", "parameters": {}, "initial_cash": "1000"})
    assert result.status_code == 400
    assert "覆盖" in result.json["error"]


def test_network_failure_reuses_timestamped_cache(tmp_path):
    market = MarketClient()
    app = create_app(tmp_path, market_client=market)
    browser = app.test_client()
    path = "/api/candles?symbol=SOLUSDT&interval=1d&start=2024-01-01&end=2024-04-15"
    first = browser.get(path)
    assert first.status_code == 200
    def offline(*_args): raise MarketUnavailable("offline")
    market.candles = offline
    cached = browser.get(path)
    assert cached.status_code == 200
    assert cached.json["source"].startswith("cache:")
    assert cached.json["fetched_at"] == first.json["fetched_at"]


def test_home_has_chart_and_simulation_status(tmp_path):
    browser, _ = client(tmp_path)
    page = browser.get("/").get_data(as_text=True)
    assert "chart" in page
    assert "模拟" in page
    assert "数据来源" in page
    assert "TradingView" in page
    assert 'id="market-list"' in page
    assert 'id="market-search"' in page
    assert 'id="range-start"' in page
    assert 'id="range-end"' in page
    assert 'id="insight-volume"' in page
    assert 'id="order-book"' in page
    assert 'id="order-book-status"' in page
    assert 'id="strategy-source-list"' in page
    assert "binance_paper_trade" in page
    assert "hbot start" in page
    assert 'src="/static/market_analytics.js"' in page
    assert 'id="book-balance-5"' in page
    assert 'id="book-balance-change"' in page
    assert 'id="book-trend"' in page
    assert 'id="book-trend-range"' in page
    assert 'id="tape-buy-share"' in page
    assert 'id="recent-trades"' in page
    assert 'id="chart-live-status"' in page
    assert "wss://data-stream.binance.vision" in browser.get("/").headers["Content-Security-Policy"]
    assert browser.get("/static/vendor/lightweight-charts.standalone.production.js").status_code == 200


def test_current_day_chart_includes_open_hour_but_backtest_excludes_it(tmp_path):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    start = today - timedelta(days=5)
    requested_end = today + timedelta(days=1)

    class CurrentMarketClient:
        def __init__(self): self.ends = []
        def candles(self, symbol, interval, range_start, range_end):
            self.ends.append(range_end)
            actual_end = min(range_end, current_hour + timedelta(hours=1))
            count = int((actual_end - range_start) / timedelta(hours=1))
            bars = tuple(Candle(range_start + timedelta(hours=i), Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100)) for i in range(count))
            return MarketData("binance", "spot", symbol, interval, bars, "fixture", now, checksum_candles(bars))

    market = CurrentMarketClient()
    app = create_app(tmp_path, market_client=market)
    app.testing = True
    browser = app.test_client()
    path = f"/api/candles?symbol=BTCUSDT&interval=1h&start={start.date()}&end={requested_end.date()}"
    chart = browser.get(path)
    assert chart.status_code == 200
    assert chart.json["candles"][-1]["time"] == int(current_hour.timestamp())
    assert chart.json["last_candle_open"] is True
    assert market.ends[-1] == current_hour + timedelta(hours=1)

    browser.get("/health")
    csrf = browser.get_cookie("csrf_token").value
    headers = {"Host": "localhost", "Origin": "http://localhost", "X-App-Request": "1", "X-CSRF-Token": csrf}
    result = browser.post("/api/backtests", headers=headers, json={"symbol": "BTCUSDT", "interval": "1h", "start": str(start.date()), "end": str(requested_end.date()), "kind": "buy_hold", "parameters": {}, "initial_cash": "1000"})
    assert result.status_code == 201
    assert market.ends[-1] == current_hour
