from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_app.backtest import load_backtest, run_backtest, save_backtest
from crypto_app.market import Candle, MarketData, checksum_candles
from crypto_app.store import open_store
from crypto_app.strategy import StrategySpec


def data(closes=None, interval="1h"):
    closes = closes or [10] * 105
    step = timedelta(hours=1) if interval == "1h" else timedelta(days=1)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = tuple(Candle(start + i * step, Decimal(10), Decimal(max(10, close) + 1), Decimal(min(10, close) - 1), Decimal(close), Decimal(100)) for i, close in enumerate(closes))
    return MarketData("binance", "spot", "SOLUSDT", interval, candles, "fixture", start, checksum_candles(candles))


def spec(kind="buy_hold", params=None):
    return StrategySpec(kind, params or {}, "v1", "https://example.com", "note")


def test_buy_fills_at_next_open_with_fee_and_slippage():
    result = run_backtest(data(), spec(), Decimal(100), Decimal("0.01"), Decimal("0.1"))
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.signal_at == data().candles[0].open_at
    assert fill.filled_at == data().candles[1].open_at
    assert fill.price == Decimal(11)
    assert fill.cash_after == 0
    assert fill.fee > 0
    assert result.annualized_return is None
    assert result.data_checksum == data().checksum
    assert result.strategy_version == "v1"


def test_sell_never_exceeds_position_and_last_signal_does_not_fill():
    closes = [10] * 100 + [13, 10, 7, 10, 14]
    result = run_backtest(data(closes), spec("breakout", {"window": 3}), Decimal(100), Decimal("0.01"), Decimal("0.1"))
    assert [(fill.side, fill.filled_at) for fill in result.fills] == [
        ("BUY", data(closes).candles[101].open_at),
        ("SELL", data(closes).candles[103].open_at),
    ]
    assert result.fills[1].price == Decimal(9)
    assert all(fill.cash_after >= 0 and fill.coins_after >= 0 for fill in result.fills)
    assert result.fills[1].coins_after == 0
    assert result.fees_total > 0


def test_long_result_saved_with_assumptions(tmp_path):
    store = open_store(tmp_path)
    result = run_backtest(data(interval="1d"), spec(), Decimal(100), Decimal("0.001"), Decimal("0.002"))
    assert result.annualized_return is not None
    assert result.benchmark_return is not None
    record_id = save_backtest(store, result)
    assert load_backtest(store, record_id) == result


def test_bad_inputs_do_not_produce_results():
    with pytest.raises(ValueError):
        run_backtest(data([10] * 99), spec(), Decimal(100), Decimal(0), Decimal(0))
    with pytest.raises(ValueError):
        run_backtest(data(), spec(), Decimal(-1), Decimal(0), Decimal(0))
