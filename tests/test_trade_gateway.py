from decimal import Decimal

from cryptography.fernet import Fernet

from crypto_app.secrets import SecretStore
from crypto_app.trade_gateway import BinanceTradeGateway
from crypto_app.trade_preview import ManualOrderIntent


class Response:
    def __init__(self, value): self.value = value
    def data(self): return self.value


class Rest:
    def __init__(self): self.calls = []
    def exchange_info(self, **kwargs):
        return Response({"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT", "isSpotTradingAllowed": True, "filters": [{"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"}, {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000", "tickSize": "0.01"}, {"filterType": "MIN_NOTIONAL", "minNotional": "10"}]}]})
    def ticker_price(self, **kwargs): return Response({"price": "100"})
    def get_account(self): return Response({"balances": [{"asset": "USDT", "free": "200", "locked": "20"}]})
    def order_test(self, **kwargs): self.calls.append(("test", kwargs)); return Response({})
    def new_order(self, **kwargs): self.calls.append(("new", kwargs)); return Response({"status": "NEW", "orderId": 12, "executedQty": "0"})
    def get_order(self, **kwargs): self.calls.append(("get", kwargs)); return Response({"status": "FILLED", "orderId": 12, "executedQty": "1"})
    def delete_order(self, **kwargs): self.calls.append(("cancel", kwargs)); return Response({"status": "CANCELED", "orderId": 12, "executedQty": "0.5"})


def test_sdk_adapter_maps_rules_and_uses_client_id(tmp_path):
    secrets = SecretStore(tmp_path, Fernet.generate_key())
    secrets.save("binance_trade", {"key": "key", "secret": "secret"})
    rest = Rest()
    sdk = lambda key, secret: (type("Spot", (), {"rest_api": rest})(), None)
    gateway = BinanceTradeGateway(secrets, sdk)
    assert gateway.rules("BTCUSDT")["step_size"] == "0.001"
    assert gateway.price("BTCUSDT") == Decimal("100")
    assert gateway.available("USDT") == Decimal("200")
    intent = ManualOrderIntent("BTCUSDT", "BUY", "LIMIT", Decimal("1"), Decimal("100"))
    gateway.test_order(intent)
    assert gateway.place_order(intent, "client-1")["status"] == "NEW"
    assert rest.calls[-1][1]["new_client_order_id"] == "client-1"
    assert gateway.get_order("BTCUSDT", "client-1")["executed_qty"] == "1"
    gateway.cancel_order("BTCUSDT", "client-1")
    assert rest.calls[-1][1]["orig_client_order_id"] == "client-1"
