import hmac
import json
import os
import re
import secrets
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request

from .backtest import load_backtest, run_backtest, save_backtest
from .binance_account import BinanceAccountSource
from .binance_public import BinancePublicClient, MarketUnavailable
from .market import INTERVALS, load_market_cache, save_market_cache
from .insights import calculate_insights
from .onchain import OnchainSource, validate_address
from .research import save_research
from .secrets import SecretStore
from .store import open_store
from .strategy import StrategySpec
from .trade_execution import TradeService
from .trade_gateway import BinanceTradeGateway
from .trade_preview import ManualOrderIntent
from .trade_settings import TradeSettingsStore
from .valuation import CoinGeckoPriceClient, quote_usd, summarize_assets


def create_app(runtime_dir: Path, market_client=None, account_source=None, onchain_source=None, price_client=None, trade_gateway=None) -> Flask:
    app = Flask(__name__)
    app.extensions["draining"] = threading.Event()
    app.config.update(BIND_HOST="127.0.0.1", TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"])
    app.extensions["store"] = open_store(Path(runtime_dir))
    app.extensions["market_client"] = market_client or BinancePublicClient()
    master_key = os.environ.get("CRYPTO_MASTER_KEY", "").encode()
    secret_store = SecretStore(Path(runtime_dir), master_key) if master_key else None
    app.extensions["account_source"] = account_source if account_source is not None else (BinanceAccountSource(secret_store) if secret_store else None)
    app.extensions["onchain_source"] = onchain_source or OnchainSource()
    app.extensions["price_client"] = price_client or CoinGeckoPriceClient()
    app.extensions["trade_service"] = TradeService(app.extensions["store"], TradeSettingsStore(Path(runtime_dir), secret_store), trade_gateway or BinanceTradeGateway(secret_store)) if secret_store else None
    if secret_store and secret_store.load("binance_trade"):
        app.extensions["trade_service"].recover()

    @app.before_request
    def guard_writes():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        if app.extensions["draining"].is_set():
            return jsonify(error="服务正在关闭，暂不接受新写入"), 503
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
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["start"]) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["end"]):
                raise ValueError("日期格式无效")
            start = datetime.combine(date.fromisoformat(payload["start"]), datetime.min.time(), timezone.utc)
            end = datetime.combine(date.fromisoformat(payload["end"]), datetime.min.time(), timezone.utc)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("日期必须为 YYYY-MM-DD") from error
        if start >= end:
            raise ValueError("日期范围无效")
        if (end - start) / INTERVALS[interval] > 3000:
            raise ValueError("一次最多加载 3000 根 K 线，请缩短日期范围或选择更长周期")
        try:
            data = app.extensions["market_client"].candles(symbol, interval, start, end)
        except MarketUnavailable as error:
            cached = load_market_cache(app.extensions["store"], "binance", "spot", symbol, interval, start, end - INTERVALS[interval])
            if cached is None:
                raise error
            data = cached._replace(source="cache:" + cached.source)
        if not data.candles or data.candles[0].open_at != start or data.candles[-1].open_at + INTERVALS[interval] < end:
            raise ValueError("历史数据未覆盖所请求的完整区间，请缩短日期范围")
        return data

    @app.get("/api/symbols")
    def symbols():
        market_client = app.extensions["market_client"]
        items = market_client.symbols(request.args.get("q", ""), quote=request.args.get("quote", "USDT").upper())
        return jsonify(items=[{"symbol": item.symbol, "base": item.base, "quote": item.quote, "status": item.status, "quote_volume": str(item.quote_volume) if item.quote_volume is not None else None, "change_percent": str(item.change_percent) if item.change_percent is not None else None} for item in items], stale=getattr(market_client, "catalog_stale", False))

    @app.get("/api/candles")
    def candles():
        data = market_request(request.args)
        if not data.source.startswith("cache:"):
            save_market_cache(app.extensions["store"], data)
        return jsonify(symbol=data.symbol, interval=data.interval, source=data.source, fetched_at=data.fetched_at.isoformat(), checksum=data.checksum, candles=[{"time": int(bar.open_at.timestamp()), "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close": float(bar.close), "volume": str(bar.volume)} for bar in data.candles], insights=calculate_insights(data.candles))

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
        if not data.source.startswith("cache:"):
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
        last_success = {}
        source = app.extensions["account_source"]
        if source is not None:
            try:
                balances.extend(source.balances())
            except Exception:
                errors["binance-spot"] = "币安余额暂不可用；请检查连接与同步状态"
            success_at = getattr(source, "last_success", None)
            if success_at:
                last_success["binance-spot"] = success_at.isoformat()
        address = request.args.get("address", "").strip()
        if address:
            address = validate_address(address)
            for chain_id in (1, 56):
                try:
                    snapshot = app.extensions["onchain_source"].assets(address, chain_id)
                    balances.extend(snapshot.items)
                    discovery[str(chain_id)] = {"complete": snapshot.discovery_complete, "error": snapshot.error, "observed_at": snapshot.observed_at.isoformat()}
                    success_at = getattr(app.extensions["onchain_source"], "last_success", {}).get((address, chain_id))
                    if success_at:
                        last_success[str(chain_id)] = success_at.isoformat()
                except Exception:
                    discovery[str(chain_id)] = {"complete": False, "error": "链上服务暂不可用", "observed_at": None}
                    success_at = getattr(app.extensions["onchain_source"], "last_success", {}).get((address, chain_id))
                    if success_at:
                        last_success[str(chain_id)] = success_at.isoformat()
        summary = summarize_assets(quote_usd(balances, app.extensions["price_client"]))
        groups = {"binance-spot": [], "onchain": []}
        for item in summary.items:
            row = {"source": item.balance.source, "chain_id": item.balance.chain_id, "contract": item.balance.contract, "symbol": item.balance.symbol, "quantity": str(item.balance.quantity), "observed_at": item.balance.observed_at.isoformat(), "price_usd": str(item.price_usd) if item.price_usd is not None else None, "value_usd": str(item.value_usd) if item.value_usd is not None else None, "price_source": item.price_source, "price_at": item.price_at.isoformat() if item.price_at else None}
            groups[item.balance.source].append(row)
        return jsonify(groups=groups, total_usd=str(summary.total_usd), unpriced_count=summary.unpriced_count, discovery=discovery, errors=errors, last_success=last_success, excluded="NFT、流动性池份额、借贷债务和跨链桥在途资产未计入总额")

    def trading():
        service = app.extensions["trade_service"]
        if service is None:
            raise ValueError("请先在服务环境设置 CRYPTO_MASTER_KEY")
        return service

    def order_payload(order):
        return order.__dict__

    @app.get("/api/trade/settings")
    def trade_settings():
        service = trading()
        settings = service.settings.load()
        return jsonify(enabled=settings.enabled, per_order_limit=str(settings.per_order_limit), daily_limit=str(settings.daily_limit))

    @app.post("/api/trade/settings")
    def configure_trading():
        service = trading()
        body = request.get_json(silent=True) or {}
        key, secret = str(body.get("key", "")), str(body.get("secret", ""))
        if not key or not secret:
            raise ValueError("交易 API Key 和 Secret 均不能为空")
        with service.lock:
            previous = service.settings.secrets.load("binance_trade")
            if previous and previous != {"key": key, "secret": secret} and any(order.status not in ("FILLED", "CANCELED", "REJECTED", "EXPIRED") for order in service.list()):
                raise ValueError("存在未结束订单，请先核实并处理后再更换交易密钥")
            permissions = service.gateway.permissions(key, secret)
            service.settings.configure(key, secret, permissions, str(body.get("passphrase", "")), body.get("per_order_limit"), body.get("daily_limit"))
            service.audit("trading_enabled")
        return jsonify(enabled=True)

    @app.post("/api/trade/settings/disable")
    def disable_trading():
        service = trading()
        service.settings.disable()
        service.audit("trading_disabled")
        return jsonify(enabled=False)

    @app.post("/api/trade/previews")
    def create_preview():
        body = request.get_json(silent=True) or {}
        try:
            quantity = Decimal(str(body.get("quantity", "")))
            limit_price = Decimal(str(body["limit_price"])) if body.get("limit_price") not in (None, "") else None
        except Exception as error:
            raise ValueError("数量或限价无效") from error
        intent = ManualOrderIntent(str(body.get("symbol", "")).upper(), str(body.get("side", "")).upper(), str(body.get("type", "")).upper(), quantity, limit_price)
        result = trading().preview(intent)
        return jsonify(id=result.id, symbol=intent.symbol, side=intent.side, type=intent.type, quantity=str(intent.quantity), limit_price=str(intent.limit_price) if intent.limit_price is not None else None, quote=str(result.quote), estimated_notional=str(result.estimated_notional), estimated_fee=str(result.estimated_fee), estimated_slippage=str(result.estimated_slippage), expires_at=result.expires_at.isoformat(), per_order_limit=str(trading().settings.load().per_order_limit), daily_limit=str(trading().settings.load().daily_limit)), 201

    @app.post("/api/trade/previews/<preview_id>/confirm")
    def confirm_preview(preview_id):
        body = request.get_json(silent=True) or {}
        return jsonify(order_payload(trading().confirm(preview_id, str(body.get("passphrase", "")))))

    @app.get("/api/trade/orders")
    def list_trade_orders():
        return jsonify(items=[order_payload(order) for order in trading().list()])

    @app.get("/api/trade/orders/<client_order_id>")
    def get_trade_order(client_order_id):
        return jsonify(order_payload(trading().reconcile(client_order_id)))

    @app.post("/api/trade/orders/<client_order_id>/cancel")
    def cancel_trade_order(client_order_id):
        body = request.get_json(silent=True) or {}
        return jsonify(order_payload(trading().cancel(client_order_id, str(body.get("passphrase", "")))))

    return app
