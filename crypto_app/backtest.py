import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from .market import MarketData, validate_candles
from .strategy import StrategySpec, generate_intents


class Fill(NamedTuple):
    signal_at: datetime
    filled_at: datetime
    side: str
    reason: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    cash_after: Decimal
    coins_after: Decimal


class BacktestResult(NamedTuple):
    symbol: str
    strategy_kind: str
    strategy_version: str
    parameters: dict
    data_checksum: str
    data_source: str
    initial_cash: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    fills: tuple[Fill, ...]
    total_return: Decimal
    max_drawdown: Decimal
    win_rate: Decimal
    fees_total: Decimal
    benchmark_return: Decimal
    annualized_return: Decimal | None
    final_cash: Decimal
    final_coins: Decimal
    limitation: str


LIMITATION = "OHLC K 线无法证明订单簿中的真实成交和滑点；结果只代表所列假设。"


def _execute(data, intents, initial_cash, fee_rate, slippage_rate):
    by_time = {intent.signal_at: intent for intent in intents}
    cash, coins, fees = initial_cash, Decimal(0), Decimal(0)
    fills = []
    peak = initial_cash
    max_drawdown = Decimal(0)
    wins = closed = 0
    entry_cost = Decimal(0)
    for i, bar in enumerate(data.candles):
        if i > 0:
            intent = by_time.get(data.candles[i - 1].open_at)
            if intent and intent.side == "BUY" and cash > 0:
                budget = cash * intent.fraction
                price = bar.open * (1 + slippage_rate)
                amount = budget / (1 + fee_rate)
                fee = budget - amount
                quantity = amount / price
                cash -= budget
                coins += quantity
                fees += fee
                entry_cost += budget
                fills.append(Fill(intent.signal_at, bar.open_at, "BUY", intent.reason, quantity, price, fee, cash, coins))
            elif intent and intent.side == "SELL" and coins > 0:
                quantity = coins * intent.fraction
                price = bar.open * (1 - slippage_rate)
                gross = quantity * price
                fee = gross * fee_rate
                cash += gross - fee
                coins -= quantity
                fees += fee
                closed += 1
                if gross - fee > entry_cost:
                    wins += 1
                entry_cost = 0 if coins == 0 else entry_cost * (1 - intent.fraction)
                fills.append(Fill(intent.signal_at, bar.open_at, "SELL", intent.reason, quantity, price, fee, cash, coins))
        equity = cash + coins * bar.close
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    final = cash + coins * data.candles[-1].close
    return tuple(fills), cash, coins, fees, final / initial_cash - 1, max_drawdown, (Decimal(wins) / closed if closed else Decimal(0))


def run_backtest(data: MarketData, spec: StrategySpec, initial_cash: Decimal, fee_rate: Decimal, slippage_rate: Decimal) -> BacktestResult:
    validate_candles(data)
    if initial_cash <= 0 or not 0 <= fee_rate < 1 or not 0 <= slippage_rate < 1:
        raise ValueError("初始资金、手续费或滑点无效")
    intents = generate_intents(spec, data.candles, data.symbol)
    fills, cash, coins, fees, total_return, drawdown, win_rate = _execute(data, intents, initial_cash, fee_rate, slippage_rate)
    baseline = generate_intents(StrategySpec("buy_hold", {}, "1", spec.source_url, ""), data.candles, data.symbol)
    benchmark_return = _execute(data, baseline, initial_cash, fee_rate, slippage_rate)[4]
    duration = data.candles[-1].open_at - data.candles[0].open_at
    annualized = None
    if duration >= timedelta(days=30):
        years = Decimal(str(duration.total_seconds())) / Decimal("31557600")
        annualized = Decimal(str(float(1 + total_return) ** (1 / float(years)) - 1))
    return BacktestResult(data.symbol, spec.kind, spec.version, spec.parameters, data.checksum, data.source, initial_cash, fee_rate, slippage_rate, fills, total_return, drawdown, win_rate, fees, benchmark_return, annualized, cash, coins, LIMITATION)


def save_backtest(store: sqlite3.Connection, result: BacktestResult) -> int:
    store.execute("CREATE TABLE IF NOT EXISTS backtests (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    payload = result._asdict()
    payload["fills"] = [fill._asdict() for fill in result.fills]
    cursor = store.execute("INSERT INTO backtests(payload) VALUES (?)", (json.dumps(payload, default=str),))
    store.commit()
    return cursor.lastrowid


def load_backtest(store: sqlite3.Connection, record_id: int) -> BacktestResult:
    row = store.execute("SELECT payload FROM backtests WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise LookupError("回测记录不存在")
    payload = json.loads(row[0])
    payload["fills"] = tuple(Fill(datetime.fromisoformat(fill["signal_at"]), datetime.fromisoformat(fill["filled_at"]), fill["side"], fill["reason"], *(Decimal(fill[key]) for key in ("quantity", "price", "fee", "cash_after", "coins_after"))) for fill in payload["fills"])
    for key in ("initial_cash", "fee_rate", "slippage_rate", "total_return", "max_drawdown", "win_rate", "fees_total", "benchmark_return", "final_cash", "final_coins"):
        payload[key] = Decimal(payload[key])
    if payload["annualized_return"] is not None:
        payload["annualized_return"] = Decimal(payload["annualized_return"])
    return BacktestResult(**payload)
