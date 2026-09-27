from datetime import datetime, timedelta, timezone
from decimal import Decimal

from crypto_app.app import create_app
from crypto_app.binance_public import SymbolInfo
from crypto_app.binance_public import MarketUnavailable
from crypto_app.market import Candle, MarketData, checksum_candles


class MarketClient:
    def symbols(self, query):
        items = [SymbolInfo("BTCUSDT", "BTC", "USDT", "TRADING", Decimal("1000")), SymbolInfo("SOLUSDT", "SOL", "USDT", "TRADING", Decimal("200"))]
        return [item for item in items if query.upper() in item.symbol]

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
    assert [item["symbol"] for item in browser.get("/api/symbols?q=SOL").json["items"]] == ["SOLUSDT"]
    candles = browser.get("/api/candles?symbol=SOLUSDT&interval=1d&start=2024-01-01&end=2024-04-15")
    assert candles.status_code == 200
    assert len(candles.json["candles"]) == 105
    assert candles.json["source"] == "fixture"
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
    assert browser.get("/static/vendor/lightweight-charts.standalone.production.js").status_code == 200
