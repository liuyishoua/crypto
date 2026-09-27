import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from .backtest import load_backtest, run_backtest, save_backtest
from .binance_public import BinancePublicClient, MarketUnavailable
from .market import INTERVALS, save_market_cache
from .research import save_research
from .store import open_store
from .strategy import StrategySpec


def create_app(runtime_dir: Path, market_client=None) -> Flask:
    app = Flask(__name__)
    app.config.update(BIND_HOST="127.0.0.1", TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    app.extensions["store"] = open_store(Path(runtime_dir))
    app.extensions["market_client"] = market_client or BinancePublicClient()

    @app.before_request
    def guard_writes():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        origin = request.headers.get("Origin", "")
        parsed = urlsplit(origin)
        token = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get("csrf_token", "")
        if (
            request.headers.get("X-App-Request") != "1"
            or not origin
            or parsed.scheme != request.scheme
            or parsed.netloc != request.host
            or not token
            or not cookie
            or not hmac.compare_digest(token, cookie)
        ):
            return jsonify(error="请求来源无效"), 403

    @app.after_request
    def secure_headers(response):
        if not request.cookies.get("csrf_token"):
            response.set_cookie("csrf_token", secrets.token_urlsafe(32), httponly=False, samesite="Strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(ValueError)
    def bad_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(MarketUnavailable)
    def unavailable(error):
        return jsonify(error=str(error), cached_at=error.cached_at.isoformat() if error.cached_at else None), 503

    @app.errorhandler(LookupError)
    def missing(error):
        return jsonify(error=str(error)), 404

    @app.get("/")
    def home():
        return render_template("index.html")

    def market_request(payload):
        symbol = str(payload.get("symbol", "")).upper()
        interval = payload.get("interval", "1d")
        if not re.fullmatch(r"[A-Z0-9]{4,24}", symbol) or interval not in INTERVALS:
            raise ValueError("交易对或 K 线周期无效")
        try:
            start = datetime.fromisoformat(payload["start"]).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(payload["end"]).replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("日期必须为 YYYY-MM-DD") from error
        if start >= end:
            raise ValueError("日期范围无效")
        return app.extensions["market_client"].candles(symbol, interval, start, end)

    @app.get("/api/symbols")
    def symbols():
        items = app.extensions["market_client"].symbols(request.args.get("q", ""))
        return jsonify(items=[{"symbol": item.symbol, "base": item.base, "quote": item.quote, "status": item.status, "quote_volume": str(item.quote_volume) if item.quote_volume is not None else None} for item in items])

    @app.get("/api/candles")
    def candles():
        data = market_request(request.args)
        save_market_cache(app.extensions["store"], data)
        return jsonify(symbol=data.symbol, interval=data.interval, source=data.source, fetched_at=data.fetched_at.isoformat(), checksum=data.checksum, candles=[{"time": int(bar.open_at.timestamp()), "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close": float(bar.close), "volume": str(bar.volume)} for bar in data.candles])

    @app.post("/api/research")
    def research():
        body = request.get_json(silent=True) or {}
        spec = StrategySpec(str(body.get("kind", "")), body.get("parameters", {}), str(body.get("version", "1")), str(body.get("source_url", "")), str(body.get("note", "")))
        record_id = save_research(app.extensions["store"], spec)
        return jsonify(id=record_id), 201

    def result_payload(result):
        payload = result._asdict()
        payload["fills"] = [fill._asdict() for fill in result.fills]
        return json.loads(json.dumps(payload, default=str))

    @app.get("/api/backtests")
    def backtest_list():
        store = app.extensions["store"]
        store.execute("CREATE TABLE IF NOT EXISTS backtests (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        rows = store.execute("SELECT id, payload FROM backtests ORDER BY id DESC LIMIT 100").fetchall()
        return jsonify(items=[{"id": row[0], "symbol": json.loads(row[1])["symbol"], "strategy_kind": json.loads(row[1])["strategy_kind"], "total_return": json.loads(row[1])["total_return"]} for row in rows])

    @app.post("/api/backtests")
    def backtests():
        body = request.get_json(silent=True) or {}
        data = market_request(body)
        save_market_cache(app.extensions["store"], data)
        spec = StrategySpec(str(body.get("kind", "buy_hold")), body.get("parameters", {}), "1", str(body.get("source_url", "https://example.org/own-rule")), str(body.get("note", "")))
        result = run_backtest(data, spec, Decimal(str(body.get("initial_cash", "1000"))), Decimal(str(body.get("fee_rate", "0.001"))), Decimal(str(body.get("slippage_rate", "0.001"))))
        record_id = save_backtest(app.extensions["store"], result)
        return jsonify(id=record_id, result=result_payload(result)), 201

    @app.get("/api/backtests/<int:record_id>")
    def backtest_record(record_id):
        return jsonify(result_payload(load_backtest(app.extensions["store"], record_id)))

    return app
