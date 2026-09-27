import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


class SecretStore:
    def __init__(self, runtime_dir: Path, master_key: bytes):
        if not master_key:
            raise ValueError("未设置凭证加密主密钥")
        self.fernet = Fernet(master_key)
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.runtime_dir / "secrets.bin"

    def save(self, name: str, value: dict) -> None:
        if name not in ("binance_read", "binance_trade"):
            raise ValueError("未知凭证槽位")
        contents = self._all()
        contents[name] = value
        encrypted = self.fernet.encrypt(json.dumps(contents).encode())
        fd, temporary = tempfile.mkstemp(dir=self.runtime_dir)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, name: str) -> dict | None:
        return self._all().get(name)

    def _all(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.fernet.decrypt(self.path.read_bytes()))
