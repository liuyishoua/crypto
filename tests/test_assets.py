from datetime import datetime, timedelta, timezone
from decimal import Decimal

from crypto_app.app import create_app
from crypto_app.binance_account import AssetBalance
from crypto_app.onchain import AssetSnapshot
from crypto_app.valuation import PriceQuote, quote_usd, summarize_assets


NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)


def balance(chain_id, contract, symbol, quantity=1):
    return AssetBalance("onchain", chain_id, contract, symbol, Decimal(quantity), NOW)


class Prices:
    def __init__(self, now=NOW):
        self.now = now

    def quote(self, item):
        if item.contract == "0x1":
            return PriceQuote(Decimal(1), self.now, "coingecko:eth")
        if item.contract == "0x2":
            return PriceQuote(Decimal(2), self.now, "coingecko:bsc")
        if item.contract == "stale":
            return PriceQuote(Decimal(100), NOW - timedelta(hours=2), "coingecko")
        if item.contract == "broken":
            raise OSError("price offline")
        return None


def test_same_symbol_uses_chain_and_contract_and_unpriced_not_zero():
    items = [balance(1, "0x1", "USDC"), balance(56, "0x2", "USDC"), balance(1, "stale", "OLD"), balance(1, "broken", "ERR")]
    valued = quote_usd(items, Prices(), now=NOW)
    summary = summarize_assets(valued)
    assert summary.total_usd == Decimal(3)
    assert summary.unpriced_count == 2
    assert valued[0].price_source == "coingecko:eth"
    assert valued[1].value_usd == Decimal(2)
    assert valued[2].value_usd is None
    assert valued[3].value_usd is None


class Account:
    def connect(self, key, secret):
        self.connected = True

    def balances(self):
        return [AssetBalance("binance-spot", None, None, "BTC", Decimal("0.5"), NOW)]


class Onchain:
    def assets(self, address, chain_id):
        return AssetSnapshot([balance(chain_id, "0x1" if chain_id == 1 else "0x2", "USDC")], NOW, chain_id == 1, "indexer offline" if chain_id == 56 else None)


def test_assets_endpoint_preserves_sources_and_incomplete_discovery(tmp_path):
    app = create_app(tmp_path, account_source=Account(), onchain_source=Onchain(), price_client=Prices(datetime.now(timezone.utc)))
    client = app.test_client()
    response = client.get("/api/assets?address=0x000000000000000000000000000000000000dEaD")
    assert response.status_code == 200
    assert response.json["total_usd"] == "3"
    assert response.json["unpriced_count"] == 1
    assert len(response.json["groups"]["binance-spot"]) == 1
    assert len(response.json["groups"]["onchain"]) == 2
    assert not response.json["discovery"]["56"]["complete"]
    assert response.json["groups"]["onchain"][0]["observed_at"]
    page = client.get("/").get_data(as_text=True)
    assert "未计价" in page
    assert "NFT" in page
    assert "MetaMask Connect" in page


def test_read_key_endpoint_never_returns_secret(tmp_path):
    account = Account()
    app = create_app(tmp_path, account_source=account, onchain_source=Onchain(), price_client=Prices())
    client = app.test_client()
    client.get("/health")
    csrf = client.get_cookie("csrf_token").value
    response = client.post("/api/binance/read-credentials", json={"key": "private-key", "secret": "private-secret"}, headers={"Origin": "http://localhost", "X-App-Request": "1", "X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert account.connected
    assert "private-secret" not in response.get_data(as_text=True)


def test_failed_binance_sync_exposes_last_success_time(tmp_path):
    class FailingAccount:
        last_success = NOW
        def balances(self): raise OSError("offline")

    app = create_app(tmp_path, account_source=FailingAccount(), onchain_source=Onchain(), price_client=Prices())
    data = app.test_client().get("/api/assets").json
    assert data["errors"]["binance-spot"]
    assert data["last_success"]["binance-spot"] == NOW.isoformat()
