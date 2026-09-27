from datetime import timedelta
from decimal import Decimal
from typing import NamedTuple, Sequence

from .market import Candle


class OrderIntent(NamedTuple):
    signal_at: object
    symbol: str
    side: str
    fraction: Decimal
    reason: str


class StrategySpec(NamedTuple):
    kind: str
    parameters: dict
    version: str
    source_url: str
    note: str


DESCRIPTIONS = {
    "sma_cross": "短均线上穿长均线买入，下穿卖出；仅使用已收盘 K 线。",
    "breakout": "收盘价突破此前窗口最高价买入，跌破此前窗口最低价卖出。",
    "dca": "按 UTC 固定天数间隔定投，每次投入设定比例的可用现金。",
    "buy_hold": "首根已收盘 K 线后买入并持有，作为比较基准。",
}


def _positive_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > 10_000:
        raise ValueError(f"{label} 必须是合理的正整数")
    return value


def generate_intents(spec: StrategySpec, candles: Sequence[Candle], symbol: str = "") -> list[OrderIntent]:
    kind = spec.kind
    p = spec.parameters
    if kind not in DESCRIPTIONS:
        raise ValueError("未知策略")
    if kind == "sma_cross":
        short = _positive_int(p.get("short"), "短周期")
        long = _positive_int(p.get("long"), "长周期")
        if short >= long:
            raise ValueError("短周期必须小于长周期")
    elif kind == "breakout":
        window = _positive_int(p.get("window"), "突破窗口")
    elif kind == "dca":
        days = _positive_int(p.get("every_days"), "定投周期")
        fraction = Decimal(str(p.get("fraction", "0.1")))
        if not 0 < fraction <= 1:
            raise ValueError("定投比例必须介于 0 和 1")
    if not candles:
        return []
    if kind == "buy_hold":
        return [OrderIntent(candles[0].open_at, symbol, "BUY", Decimal(1), "买入持有基准")]
    if kind == "dca":
        next_at = candles[0].open_at
        result = []
        for bar in candles:
            if bar.open_at >= next_at:
                result.append(OrderIntent(bar.open_at, symbol, "BUY", fraction, "定投周期到期"))
                next_at += timedelta(days=days)
        return result
    result = []
    if kind == "sma_cross":
        for i in range(long, len(candles)):
            recent_short = sum((bar.close for bar in candles[i-short+1:i+1]), Decimal(0)) / short
            recent_long = sum((bar.close for bar in candles[i-long+1:i+1]), Decimal(0)) / long
            prior_short = sum((bar.close for bar in candles[i-short:i]), Decimal(0)) / short
            prior_long = sum((bar.close for bar in candles[i-long:i]), Decimal(0)) / long
            if prior_short <= prior_long and recent_short > recent_long:
                result.append(OrderIntent(candles[i].open_at, symbol, "BUY", Decimal(1), "短均线上穿长均线"))
            elif prior_short >= prior_long and recent_short < recent_long:
                result.append(OrderIntent(candles[i].open_at, symbol, "SELL", Decimal(1), "短均线下穿长均线"))
    else:
        for i in range(window, len(candles)):
            previous = candles[i-window:i]
            if candles[i].close > max(bar.high for bar in previous):
                result.append(OrderIntent(candles[i].open_at, symbol, "BUY", Decimal(1), "突破此前窗口最高价"))
            elif candles[i].close < min(bar.low for bar in previous):
                result.append(OrderIntent(candles[i].open_at, symbol, "SELL", Decimal(1), "跌破此前窗口最低价"))
    return result
