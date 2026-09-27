import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from .trade_settings import TradeSettings


@dataclass(frozen=True)
class ManualOrderIntent:
    symbol: str
    side: str
    type: str
    quantity: Decimal
    limit_price: Decimal | None


@dataclass(frozen=True)
class OrderPreview:
    id: str
    intent: ManualOrderIntent
    quote: Decimal
    estimated_notional: Decimal
    estimated_fee: Decimal
    estimated_slippage: Decimal
    expires_at: datetime
    rules_snapshot: str


def _decimal(value, name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as error:
        raise ValueError(f"{name}无效") from error
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name}必须大于零")
    return result


def rules_digest(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True, default=str).encode()).hexdigest()


def preview_order(intent: ManualOrderIntent, exchange, settings: TradeSettings, now: datetime, *, daily_used=Decimal(0)) -> OrderPreview:
    if not settings.enabled:
        raise ValueError("真实交易尚未启用")
    if not re.fullmatch(r"[A-Z0-9]{4,24}", intent.symbol) or intent.side not in ("BUY", "SELL") or intent.type not in ("LIMIT", "MARKET"):
        raise ValueError("交易对、方向或订单类型无效")
    quantity = _decimal(intent.quantity, "数量")
    if intent.type == "LIMIT":
        price = _decimal(intent.limit_price, "限价")
    elif intent.limit_price is not None:
        raise ValueError("市价单不可填写限价")
    else:
        price = _decimal(exchange.price(intent.symbol), "报价")
    rules = exchange.rules(intent.symbol)
    if rules["status"] != "TRADING" or rules["symbol"] != intent.symbol:
        raise ValueError("交易对当前不可交易")
    min_qty = _decimal(rules["min_qty"], "最小数量")
    max_qty = _decimal(rules["max_qty"], "最大数量")
    step = _decimal(rules["step_size"], "数量步进")
    if quantity < min_qty or quantity > max_qty or quantity % step != 0:
        raise ValueError("数量不符合交易所过滤规则")
    if intent.type == "LIMIT":
        min_price = _decimal(rules["min_price"], "最小价格")
        max_price = _decimal(rules["max_price"], "最大价格")
        tick = _decimal(rules["tick_size"], "价格步进")
        if price < min_price or price > max_price or price % tick != 0:
            raise ValueError("限价不符合交易所过滤规则")
    notional = quantity * price
    if notional < _decimal(rules["min_notional"], "最小名义金额") or notional > _decimal(rules["max_notional"], "最大名义金额"):
        raise ValueError("金额不符合交易所过滤规则")
    slippage = notional * Decimal("0.005") if intent.type == "MARKET" else Decimal(0)
    fee = (notional + slippage) * Decimal("0.001")
    conservative = notional + slippage + fee
    if conservative > settings.per_order_limit or conservative + Decimal(daily_used) > settings.daily_limit:
        raise ValueError("超过单笔或单日交易限额")
    asset = rules["quote"] if intent.side == "BUY" else rules["base"]
    required = conservative if intent.side == "BUY" else quantity
    if exchange.available(asset) < required:
        raise ValueError("可用余额不足")
    exchange.test_order(intent)
    return OrderPreview(uuid.uuid4().hex, intent, price, notional, fee, slippage, now + timedelta(seconds=30), rules_digest(rules))
