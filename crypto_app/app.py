import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from .backtest import load_backtest, run_backtest, save_backtest
from .binance_account import BinanceAccountSource
from .binance_public import BinancePublicClient, MarketUnavailable
from .market import INTERVALS, save_market_cache
from .onchain import OnchainSource, validate_address
from .research import save_research
from .secrets import SecretStore
from .store import open_store
from .strategy import StrategySpec
from .valuation import CoinGeckoPriceClient, quote_usd, summarize_assets


def create_app(runtime_dir: Path, market_client=None, account_source=None, onchain_source=None, price_client=None) -> Flask:
    app = Flask(__name__)
    app.config.update(BIND_HOST="127.0.0.1", TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    app.extensions["store"] = open_store(Path(runtime_dir))
    app.extensions["market_client"] = market_client or BinancePublicClient()
    master_key = os.environ.get("CRYPTO_MASTER_KEY", "").encode()
    app.extensions["account_source"] = account_source if account_source is not None else (BinanceAccountSource(SecretStore(Path(runtime_dir), master_key)) if master_key else None)
    app.extensions["onchain_source"] = onchain_source or OnchainSource()
    app.extensions["price_client"] = price_client or CoinGeckoPriceClient()

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
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' wss://mm-sdk-relay.api.cx.metamask.io https://ethereum-rpc.publicnode.com https://bsc-rpc.publicnode.com; frame-ancestors 'none'"
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

    @app.post("/api/binance/read-credentials")
    def connect_read_key():
        source = app.extensions["account_source"]
        if source is None:
            return jsonify(error="请先在服务环境设置 CRYPTO_MASTER_KEY"), 503
        body = request.get_json(silent=True) or {}
        source.connect(str(body.get("key", "")), str(body.get("secret", "")))
        return jsonify(status="connected")

    @app.get("/api/assets")
    def assets():
        balances = []
        errors = {}
        discovery = {}
        source = app.extensions["account_source"]
        if source is not None:
            try:
                balances.extend(source.balances())
            except Exception:
                errors["binance-spot"] = "币安余额暂不可用；请检查连接与同步状态"
        address = request.args.get("address", "").strip()
        if address:
            address = validate_address(address)
            for chain_id in (1, 56):
                try:
                    snapshot = app.extensions["onchain_source"].assets(address, chain_id)
                    balances.extend(snapshot.items)
                    discovery[str(chain_id)] = {"complete": snapshot.discovery_complete, "error": snapshot.error, "observed_at": snapshot.observed_at.isoformat()}
                except Exception:
                    discovery[str(chain_id)] = {"complete": False, "error": "链上服务暂不可用", "observed_at": None}
        summary = summarize_assets(quote_usd(balances, app.extensions["price_client"]))
        groups = {"binance-spot": [], "onchain": []}
        for item in summary.items:
            row = {"source": item.balance.source, "chain_id": item.balance.chain_id, "contract": item.balance.contract, "symbol": item.balance.symbol, "quantity": str(item.balance.quantity), "observed_at": item.balance.observed_at.isoformat(), "price_usd": str(item.price_usd) if item.price_usd is not None else None, "value_usd": str(item.value_usd) if item.value_usd is not None else None, "price_source": item.price_source, "price_at": item.price_at.isoformat() if item.price_at else None}
            groups[item.balance.source].append(row)
        return jsonify(groups=groups, total_usd=str(summary.total_usd), unpriced_count=summary.unpriced_count, discovery=discovery, errors=errors, excluded="NFT、流动性池份额、借贷债务和跨链桥在途资产未计入总额")

    return app
