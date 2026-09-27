from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_app.trade_preview import ManualOrderIntent, preview_order
from crypto_app.trade_settings import TradeSettings


NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


class Exchange:
    def __init__(self):
        self.status = "TRADING"
        self.usdt = Decimal("500")
        self.tested = 0

    def rules(self, symbol):
        return {"symbol": symbol, "status": self.status, "base": "BTC", "quote": "USDT", "min_qty": "0.001", "max_qty": "10", "step_size": "0.001", "min_price": "0.01", "max_price": "1000000", "tick_size": "0.01", "min_notional": "10", "max_notional": "100000"}

    def price(self, symbol):
        return Decimal("100")

    def available(self, asset):
        return self.usdt if asset == "USDT" else Decimal("2")

    def test_order(self, intent):
        self.tested += 1


SETTINGS = TradeSettings(True, Decimal("200"), Decimal("500"), "hash")


def test_preview_limits_and_test_order():
    exchange = Exchange()
    order = ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("1"), Decimal("100"))
    result = preview_order(order, exchange, SETTINGS, NOW)
    assert result.estimated_notional == Decimal("100")
    assert result.estimated_fee > 0 and result.estimated_slippage == 0
    assert result.expires_at == NOW + timedelta(seconds=30)
    assert result.rules_snapshot and exchange.tested == 1


@pytest.mark.parametrize("intent", [
    ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("0.0005"), Decimal("100")),
    ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("0.0015"), Decimal("100")),
    ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("1"), Decimal("100.001")),
    ManualOrderIntent("BTCUSDT", "BUY", "MARKET", Decimal("3"), None),
])
def test_rejects_invalid_or_over_limit(intent):
    exchange = Exchange()
    with pytest.raises(ValueError):
        preview_order(intent, exchange, SETTINGS, NOW)
    assert exchange.tested == 0


def test_rejects_closed_pair_balance_and_daily_limit():
    exchange = Exchange()
    order = ManualOrderIntent("BTCUSDT", "BUY", "MARKET", Decimal("1"), None)
    exchange.status = "BREAK"
    with pytest.raises(ValueError): preview_order(order, exchange, SETTINGS, NOW)
    exchange.status = "TRADING"
    exchange.usdt = Decimal("50")
    with pytest.raises(ValueError): preview_order(order, exchange, SETTINGS, NOW)
    exchange.usdt = Decimal("500")
    with pytest.raises(ValueError): preview_order(order, exchange, SETTINGS, NOW, daily_used=Decimal("450"))
