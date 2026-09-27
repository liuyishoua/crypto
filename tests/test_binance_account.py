from datetime import timezone
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from crypto_app.binance_account import BinanceAccountSource
from crypto_app.secrets import SecretStore


class Response:
    def __init__(self, data):
        self.value = data

    def data(self):
        return self.value


class Api:
    def __init__(self, permission):
        self.permission = permission

    def get_api_key_permission(self):
        return Response(self.permission)

    def get_account(self):
        return Response({"balances": [{"asset": "BTC", "free": "0.25", "locked": "0.10"}, {"asset": "SOL", "free": "2", "locked": "0"}], "canWithdraw": False})


class Client:
    def __init__(self, api):
        self.rest_api = api


def factory(permission):
    return lambda key, secret: (Client(Api(permission)), Client(Api(permission)))


def test_read_only_connection_encrypts_and_reads_balances(tmp_path):
    secrets = SecretStore(tmp_path, Fernet.generate_key())
    source = BinanceAccountSource(secrets, factory({"enableReading": True, "enableWithdrawals": False, "enableSpotAndMarginTrading": False}))
    source.connect("KEY-SENSITIVE", "SECRET-SENSITIVE")
    assert b"SECRET-SENSITIVE" not in (tmp_path / "secrets.bin").read_bytes()
    balances = source.balances()
    assert [(item.symbol, item.quantity) for item in balances] == [("BTC", Decimal("0.35")), ("SOL", Decimal("2"))]
    assert balances[0].source == "binance-spot"
    assert balances[0].observed_at.tzinfo == timezone.utc
    assert source.last_success is not None


def test_withdrawal_permission_is_rejected(tmp_path):
    secrets = SecretStore(tmp_path, Fernet.generate_key())
    source = BinanceAccountSource(secrets, factory({"enableReading": True, "enableWithdrawals": True, "enableSpotAndMarginTrading": False}))
    with pytest.raises(ValueError, match="提现"):
        source.connect("key", "secret")
    assert not (tmp_path / "secrets.bin").exists()


def test_missing_master_key_cannot_save(tmp_path):
    with pytest.raises(ValueError, match="主密钥"):
        SecretStore(tmp_path, b"")
