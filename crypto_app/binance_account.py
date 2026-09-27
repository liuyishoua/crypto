from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from .secrets import SecretStore


@dataclass(frozen=True)
class AssetBalance:
    source: str
    chain_id: int | None
    contract: str | None
    symbol: str
    quantity: Decimal
    observed_at: datetime


def _field(record, camel: str, snake: str):
    if isinstance(record, dict):
        return record.get(camel, record.get(snake))
    return getattr(record, snake, getattr(record, camel, None))


def sdk_clients(key: str, secret: str):
    from binance_common.configuration import ConfigurationRestAPI
    from binance_sdk_spot.spot import Spot
    from binance_sdk_wallet.wallet import Wallet

    configuration = ConfigurationRestAPI(api_key=key, api_secret=secret)
    return Spot(config_rest_api=configuration), Wallet(config_rest_api=configuration)


class BinanceAccountSource:
    def __init__(self, secrets: SecretStore, sdk_factory: Callable = sdk_clients):
        self.secrets = secrets
        self.sdk_factory = sdk_factory
        self.last_success = None
        self.last_error = None

    def _permissions(self, wallet):
        permission = wallet.rest_api.get_api_key_permission().data()
        if not _field(permission, "enableReading", "enable_reading"):
            raise ValueError("币安密钥未启用读取权限")
        if _field(permission, "enableWithdrawals", "enable_withdrawals"):
            raise ValueError("拒绝具有提现权限的密钥")
        if _field(permission, "enableSpotAndMarginTrading", "enable_spot_and_margin_trading"):
            raise ValueError("只读密钥不得启用交易权限")
        return permission

    def connect(self, key: str, secret: str) -> None:
        if not key or not secret:
            raise ValueError("API Key 和 Secret 均不能为空")
        spot, wallet = self.sdk_factory(key, secret)
        self._permissions(wallet)
        account = spot.rest_api.get_account().data()
        if _field(account, "canWithdraw", "can_withdraw"):
            raise ValueError("账户响应显示提现权限，拒绝连接")
        self.secrets.save("binance_read", {"key": key, "secret": secret})

    def balances(self) -> list[AssetBalance]:
        credential = self.secrets.load("binance_read")
        if credential is None:
            raise ValueError("尚未连接币安只读账户")
        try:
            spot, wallet = self.sdk_factory(credential["key"], credential["secret"])
            self._permissions(wallet)
            account = spot.rest_api.get_account().data()
            observed_at = datetime.now(timezone.utc)
            balances = []
            for row in _field(account, "balances", "balances") or []:
                quantity = Decimal(str(_field(row, "free", "free"))) + Decimal(str(_field(row, "locked", "locked")))
                if quantity:
                    balances.append(AssetBalance("binance-spot", None, None, str(_field(row, "asset", "asset")), quantity, observed_at))
            self.last_success = observed_at
            self.last_error = None
            return balances
        except Exception as error:
            self.last_error = str(error)
            raise
