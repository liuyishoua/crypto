from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from crypto_app.secrets import SecretStore
from crypto_app.store import open_store
from crypto_app.trade_execution import TradeService
from crypto_app.trade_preview import ManualOrderIntent
from crypto_app.trade_settings import TradeSettingsStore


class Exchange:
    def __init__(self):
        self.sent = 0
        self.cancelled = 0
        self.status = "NEW"
        self.timeout = False
        self.free = Decimal("1000")

    def rules(self, symbol):
        return {"symbol": symbol, "status": "TRADING", "base": "BTC", "quote": "USDT", "min_qty": "0.001", "max_qty": "10", "step_size": "0.001", "min_price": "0.01", "max_price": "1000000", "tick_size": "0.01", "min_notional": "10", "max_notional": "100000"}

    def price(self, symbol): return Decimal("100")
    def available(self, asset): return self.free
    def test_order(self, intent): pass

    def place_order(self, intent, client_id):
        self.sent += 1
        if self.timeout: raise TimeoutError("network timeout")
        return {"status": self.status, "order_id": 123, "executed_qty": "0"}

    def get_order(self, symbol, client_id):
        if self.timeout: raise TimeoutError("lookup timeout")
        return {"status": self.status, "order_id": 123, "executed_qty": "0.5" if self.status == "PARTIALLY_FILLED" else "0"}

    def cancel_order(self, symbol, client_id):
        self.cancelled += 1
        self.status = "CANCELED"
        return self.get_order(symbol, client_id)


def service(tmp_path, exchange=None):
    secrets = SecretStore(tmp_path, Fernet.generate_key())
    settings = TradeSettingsStore(tmp_path, secrets)
    settings.configure("trade", "secret", {"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}, "long unlock phrase", "200", "500")
    return TradeService(open_store(tmp_path), settings, exchange or Exchange())


def test_duplicate_confirmation_sends_once_and_reconciles(tmp_path):
    exchange = Exchange()
    trade = service(tmp_path, exchange)
    preview = trade.preview(ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("1"), Decimal("100")))
    first = trade.confirm(preview.id, "long unlock phrase")
    second = trade.confirm(preview.id, "long unlock phrase")
    assert exchange.sent == 1
    assert first.client_order_id == second.client_order_id
    exchange.status = "PARTIALLY_FILLED"
    assert trade.reconcile(first.client_order_id).status == "PARTIALLY_FILLED"
    assert trade.cancel(first.client_order_id, "long unlock phrase").status == "CANCELED"
    assert exchange.cancelled == 1


def test_timeout_or_restart_never_resends(tmp_path):
    exchange = Exchange()
    trade = service(tmp_path, exchange)
    preview = trade.preview(ManualOrderIntent("BTCUSDT", "BUY", "MARKET", Decimal("1"), None))
    exchange.timeout = True
    result = trade.confirm(preview.id, "long unlock phrase")
    assert result.status == "UNCERTAIN" and exchange.sent == 1
    restarted = TradeService(open_store(tmp_path), trade.settings, exchange)
    assert restarted.confirm(preview.id, "long unlock phrase").status == "UNCERTAIN"
    assert exchange.sent == 1
    exchange.timeout = False
    exchange.status = "FILLED"
    assert restarted.reconcile(result.client_order_id).status == "FILLED"


def test_expired_rechecked_and_unlock_required(tmp_path):
    exchange = Exchange()
    trade = service(tmp_path, exchange)
    preview = trade.preview(ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("1"), Decimal("100")))
    with pytest.raises(ValueError): trade.confirm(preview.id, "wrong")
    exchange.free = Decimal("1")
    with pytest.raises(ValueError): trade.confirm(preview.id, "long unlock phrase")
    exchange.free = Decimal("1000")
    with pytest.raises(ValueError): trade.confirm(preview.id, "long unlock phrase", now=preview.expires_at + timedelta(seconds=1))
    assert exchange.sent == 0
