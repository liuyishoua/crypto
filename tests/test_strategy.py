from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_app.market import Candle
from crypto_app.research import load_research, save_research
from crypto_app.store import open_store
from crypto_app.strategy import StrategySpec, generate_intents


def bars(closes):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Candle(start + timedelta(days=i), Decimal(str(price)), Decimal(str(price + 1)), Decimal(str(price - 1)), Decimal(str(price)), Decimal("100")) for i, price in enumerate(closes)]


def spec(kind, params):
    return StrategySpec(kind, params, "1", "https://example.com/rule", "研究记录")


def test_sma_cross_uses_only_closed_history():
    candles = bars([10, 9, 8, 9, 12, 13, 7])
    signals = generate_intents(spec("sma_cross", {"short": 2, "long": 3}), candles)
    assert [(item.side, item.signal_at) for item in signals] == [("BUY", candles[4].open_at), ("SELL", candles[6].open_at)]
    assert generate_intents(spec("sma_cross", {"short": 2, "long": 3}), candles[:4]) == []


def test_breakout_and_periodic_strategies():
    candles = bars([10, 10, 10, 12, 11, 8])
    breakout = generate_intents(spec("breakout", {"window": 3}), candles)
    assert [(item.side, item.signal_at) for item in breakout] == [("BUY", candles[3].open_at), ("SELL", candles[5].open_at)]
    dca = generate_intents(spec("dca", {"every_days": 2, "fraction": "0.2"}), candles)
    assert [item.signal_at for item in dca] == [candles[i].open_at for i in (0, 2, 4)]
    assert generate_intents(spec("buy_hold", {}), candles)[0].signal_at == candles[0].open_at


@pytest.mark.parametrize("kind,params", [("sma_cross", {"short": 0, "long": 3}), ("sma_cross", {"short": 3, "long": 2}), ("breakout", {"window": 0}), ("dca", {"every_days": -1}), ("unknown", {})])
def test_rejects_invalid_rule_parameters(kind, params):
    with pytest.raises(ValueError):
        generate_intents(spec(kind, params), bars([10, 11, 12]))


def test_research_note_is_saved_as_data(tmp_path):
    store = open_store(tmp_path)
    saved = StrategySpec("buy_hold", {}, "1", "https://example.com/strategy", "__import__('os').system('echo unsafe')")
    record_id = save_research(store, saved)
    assert load_research(store, record_id) == saved
    with pytest.raises(ValueError):
        save_research(store, StrategySpec("buy_hold", {}, "1", "file:///tmp/secret", ""))
