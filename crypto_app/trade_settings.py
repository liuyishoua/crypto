import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .secrets import SecretStore


@dataclass(frozen=True)
class TradeSettings:
    enabled: bool
    per_order_limit: Decimal
    daily_limit: Decimal
    passphrase_hash: str


def _positive(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("交易限额必须为正数") from error
    if not result.is_finite() or result <= 0:
        raise ValueError("交易限额必须为正数")
    return result


def _hash_unlock(passphrase: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_unlock(passphrase: str, stored_hash: str) -> bool:
    try:
        kind, n, r, p, salt, expected = stored_hash.split("$")
        if kind != "scrypt":
            return False
        digest = hashlib.scrypt(passphrase.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class TradeSettingsStore:
    def __init__(self, runtime_dir: Path, secrets: SecretStore):
        self.path = Path(runtime_dir) / "trade_settings.json"
        self.secrets = secrets

    def load(self) -> TradeSettings:
        if not self.path.exists():
            return TradeSettings(False, Decimal(0), Decimal(0), "")
        raw = json.loads(self.path.read_text())
        return TradeSettings(bool(raw["enabled"]), Decimal(raw["per_order_limit"]), Decimal(raw["daily_limit"]), raw["passphrase_hash"])

    def _save(self, settings: TradeSettings):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"enabled": settings.enabled, "per_order_limit": str(settings.per_order_limit), "daily_limit": str(settings.daily_limit), "passphrase_hash": settings.passphrase_hash}, stream)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def configure(self, key: str, secret: str, permissions: dict, passphrase: str, per_order_limit, daily_limit):
        if not key or not secret or not permissions.get("enableReading") or not permissions.get("enableSpotAndMarginTrading") or permissions.get("enableWithdrawals"):
            raise ValueError("交易密钥需有读取和现货交易权限，且必须关闭提现权限")
        if len(passphrase) < 12:
            raise ValueError("交易解锁口令至少 12 个字符")
        per = _positive(per_order_limit)
        daily = _positive(daily_limit)
        if daily < per:
            raise ValueError("单日限额不能小于单笔限额")
        configured = TradeSettings(True, per, daily, _hash_unlock(passphrase))
        self._save(TradeSettings(False, per, daily, configured.passphrase_hash))
        self.secrets.save("binance_trade", {"key": key, "secret": secret})
        self._save(configured)

    def disable(self):
        saved = self.load()
        self._save(TradeSettings(False, saved.per_order_limit, saved.daily_limit, saved.passphrase_hash))
