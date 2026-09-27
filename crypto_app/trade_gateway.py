from decimal import Decimal

from .binance_account import sdk_clients
from .secrets import SecretStore


def _dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True)
    raise ValueError("交易所响应格式不受支持")


class BinanceTradeGateway:
    def __init__(self, secrets: SecretStore, sdk_factory=sdk_clients):
        self.secrets = secrets
        self.sdk_factory = sdk_factory

    def permissions(self, key, secret):
        _, wallet = self.sdk_factory(key, secret)
        raw = _dict(wallet.rest_api.get_api_key_permission().data())
        return {"enableReading": raw.get("enableReading"), "enableSpotAndMarginTrading": raw.get("enableSpotAndMarginTrading"), "enableWithdrawals": raw.get("enableWithdrawals")}

    def _rest(self, *, for_write=False):
        credential = self.secrets.load("binance_trade")
        if not credential:
            raise ValueError("尚未配置交易密钥")
        if for_write:
            permission = self.permissions(credential["key"], credential["secret"])
            if not permission["enableReading"] or not permission["enableSpotAndMarginTrading"] or permission["enableWithdrawals"]:
                raise ValueError("交易密钥权限已变化；请关闭提现并重新检查密钥")
        spot, _ = self.sdk_factory(credential["key"], credential["secret"])
        return spot.rest_api

    def rules(self, symbol):
        raw = _dict(self._rest().exchange_info(symbol=symbol).data())
        matches = [_dict(item) for item in raw.get("symbols", []) if _dict(item).get("symbol") == symbol]
        if len(matches) != 1:
            raise ValueError("交易对不存在")
        item = matches[0]
        filters = {entry["filterType"]: entry for entry in (_dict(value) for value in item.get("filters", [])) if entry and "filterType" in entry}
        lot = filters.get("LOT_SIZE", {})
        market_lot = filters.get("MARKET_LOT_SIZE", {})
        price = filters.get("PRICE_FILTER", {})
        notional = filters.get("NOTIONAL", {})
        minimum = filters.get("MIN_NOTIONAL", {})
        if not lot or not price or not (notional or minimum):
            raise ValueError("交易所过滤规则不完整")
        # MARKET_LOT_SIZE may contain disabled zero fields; LOT_SIZE is the safe fallback.
        maximum = notional.get("maxNotional")
        if maximum is None or Decimal(str(maximum)) == 0:
            maximum = "1000000000000"
        return {"symbol": symbol, "status": item.get("status") if item.get("isSpotTradingAllowed", True) else "DISABLED", "base": item["baseAsset"], "quote": item["quoteAsset"], "min_qty": lot["minQty"], "max_qty": lot["maxQty"], "step_size": lot["stepSize"], "market_min_qty": market_lot.get("minQty", "0"), "market_max_qty": market_lot.get("maxQty", "0"), "market_step_size": market_lot.get("stepSize", "0"), "min_price": price["minPrice"], "max_price": price["maxPrice"], "tick_size": price["tickSize"], "min_notional": notional.get("minNotional") or minimum.get("minNotional") or "0", "max_notional": maximum}

    def price(self, symbol):
        return Decimal(str(_dict(self._rest().ticker_price(symbol=symbol).data())["price"]))

    def available(self, asset):
        account = _dict(self._rest().get_account().data())
        for raw in account.get("balances", []):
            row = _dict(raw)
            if row.get("asset") == asset:
                return Decimal(str(row["free"]))
        return Decimal(0)

    def _order_args(self, intent, client_id=None):
        # The SDK serializes these values directly into signed request parameters.
        # Decimal strings retain exchange step precision that floats would lose.
        args = {"symbol": intent.symbol, "side": intent.side, "type": intent.type, "quantity": str(intent.quantity)}
        if intent.type == "LIMIT":
            args.update(time_in_force="GTC", price=str(intent.limit_price))
        if client_id:
            args["new_client_order_id"] = client_id
        return args

    def test_order(self, intent):
        self._rest(for_write=True).order_test(**self._order_args(intent)).data()

    def place_order(self, intent, client_id):
        return self._status(self._rest(for_write=True).new_order(**self._order_args(intent, client_id)).data())

    def get_order(self, symbol, client_id):
        return self._status(self._rest().get_order(symbol=symbol, orig_client_order_id=client_id).data())

    def cancel_order(self, symbol, client_id):
        return self._status(self._rest(for_write=True).delete_order(symbol=symbol, orig_client_order_id=client_id).data())

    @staticmethod
    def _status(raw):
        row = _dict(raw)
        return {"status": row.get("status"), "order_id": row.get("orderId"), "executed_qty": row.get("executedQty", "0")}
