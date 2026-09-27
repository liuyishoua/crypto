from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from crypto_app.secrets import SecretStore
from crypto_app.trade_settings import TradeSettingsStore, verify_unlock


def test_trade_disabled_and_separate_credentials(tmp_path):
    secrets = SecretStore(tmp_path, Fernet.generate_key())
    secrets.save("binance_read", {"key": "read", "secret": "read-secret"})
    settings = TradeSettingsStore(tmp_path, secrets)
    assert not settings.load().enabled
    settings.configure("trade", "trade-secret", {"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}, "long unlock phrase", "100", "500")
    saved = settings.load()
    assert saved.enabled and saved.per_order_limit == Decimal(100)
    assert verify_unlock("long unlock phrase", saved.passphrase_hash)
    assert not verify_unlock("wrong", saved.passphrase_hash)
    assert secrets.load("binance_read")["key"] == "read"
    assert secrets.load("binance_trade")["key"] == "trade"
    assert "trade-secret" not in (tmp_path / "trade_settings.json").read_text()
    settings.disable()
    assert not settings.load().enabled


@pytest.mark.parametrize("permission,phrase,per,daily", [
    ({"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": True}, "long unlock phrase", "100", "500"),
    ({"enableReading": True, "enableSpotAndMarginTrading": False, "enableWithdrawals": False}, "long unlock phrase", "100", "500"),
    ({"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}, "short", "100", "500"),
    ({"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}, "long unlock phrase", "0", "500"),
    ({"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False}, "long unlock phrase", "100", "-1"),
])
def test_rejects_unsafe_settings(tmp_path, permission, phrase, per, daily):
    settings = TradeSettingsStore(tmp_path, SecretStore(tmp_path, Fernet.generate_key()))
    with pytest.raises(ValueError):
        settings.configure("trade", "secret", permission, phrase, per, daily)
    assert not settings.load().enabled
