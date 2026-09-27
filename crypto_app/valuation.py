from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

from .binance_account import AssetBalance


@dataclass(frozen=True)
class PriceQuote:
    price_usd: Decimal
    observed_at: datetime
    source: str


@dataclass(frozen=True)
class ValuedAsset:
    balance: AssetBalance
    price_usd: Decimal | None
    value_usd: Decimal | None
    price_source: str | None
    price_at: datetime | None


@dataclass(frozen=True)
class AssetSummary:
    items: list[ValuedAsset]
    total_usd: Decimal
    unpriced_count: int


def quote_usd(items: list[AssetBalance], price_client, *, now=None) -> list[ValuedAsset]:
    now = now or datetime.now(timezone.utc)
    valued = []
    for item in items:
        try:
            quote = price_client.quote(item)
            fresh = quote and quote.observed_at.tzinfo is not None and now - quote.observed_at <= timedelta(minutes=5)
            valid = fresh and quote.price_usd.is_finite() and quote.price_usd > 0
        except Exception:
            quote = None
            valid = False
        if valid:
            valued.append(ValuedAsset(item, quote.price_usd, item.quantity * quote.price_usd, quote.source, quote.observed_at))
        else:
            valued.append(ValuedAsset(item, None, None, None, None))
    return valued


def summarize_assets(items: list[ValuedAsset]) -> AssetSummary:
    return AssetSummary(items, sum((item.value_usd for item in items if item.value_usd is not None), Decimal(0)), sum(item.value_usd is None for item in items))


class CoinGeckoPriceClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def quote(self, item: AssetBalance) -> PriceQuote | None:
        if item.source == "onchain" and item.contract:
            network = {1: "eth", 56: "bsc"}.get(item.chain_id)
            if not network:
                return None
            response = self.session.get(f"https://api.coingecko.com/api/v3/onchain/simple/networks/{network}/token_price/{item.contract}", timeout=10)
            response.raise_for_status()
            raw = response.json().get("data", {}).get("attributes", {}).get("token_prices", {}).get(item.contract.lower())
            source = f"coingecko:{network}:{item.contract.lower()}"
        elif item.source == "onchain":
            coin = {1: "ethereum", 56: "binancecoin"}.get(item.chain_id)
            if not coin:
                return None
            response = self.session.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": coin, "vs_currencies": "usd"}, timeout=10)
            response.raise_for_status()
            raw = response.json().get(coin, {}).get("usd")
            source = f"coingecko:{coin}"
        elif item.source == "binance-spot":
            if item.symbol in ("USDT", "USDC"):
                coin = "tether" if item.symbol == "USDT" else "usd-coin"
                response = self.session.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": coin, "vs_currencies": "usd"}, timeout=10)
                response.raise_for_status()
                raw = response.json().get(coin, {}).get("usd")
                source = f"coingecko:{coin}"
            else:
                response = self.session.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{item.symbol}USDT"}, timeout=10)
                response.raise_for_status()
                raw = response.json().get("price")
                source = f"binance:{item.symbol}USDT"
        else:
            return None
        if raw is None:
            return None
        price = Decimal(str(raw))
        if not price.is_finite() or price <= 0:
            return None
        return PriceQuote(price, datetime.now(timezone.utc), source)
