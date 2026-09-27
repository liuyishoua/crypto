import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import requests
from web3 import Web3

from .binance_account import AssetBalance


RPC_URLS = {
    1: ("CRYPTO_ETH_RPC_URL", "https://ethereum-rpc.publicnode.com"),
    56: ("CRYPTO_BSC_RPC_URL", "https://bsc-rpc.publicnode.com"),
}
BLOCKSCOUT_URLS = {1: "https://eth.blockscout.com", 56: "https://bsc.blockscout.com"}
ERC20_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "owner", "type": "address"}], "outputs": [{"name": "balance", "type": "uint256"}]},
]


@dataclass(frozen=True)
class Token:
    contract: str
    symbol: str
    decimals: int


@dataclass(frozen=True)
class AssetSnapshot:
    items: list[AssetBalance]
    observed_at: datetime
    discovery_complete: bool
    error: str | None


def validate_address(address: str) -> str:
    if not isinstance(address, str) or not Web3.is_address(address):
        raise ValueError("钱包地址无效")
    return Web3.to_checksum_address(address)


def web3_for_chain(chain_id: int) -> Web3:
    variable, default = RPC_URLS[chain_id]
    return Web3(Web3.HTTPProvider(os.environ.get(variable, default), request_kwargs={"timeout": 12}))


class BlockscoutIndexer:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def discover(self, address: str, chain_id: int) -> list[Token]:
        response = self.session.get(f"{BLOCKSCOUT_URLS[chain_id]}/api/v2/addresses/{address}/token-balances", timeout=12)
        response.raise_for_status()
        found = []
        for item in response.json():
            token = item.get("token") or {}
            if token.get("type") != "ERC-20":
                continue
            contract = token.get("address_hash") or token.get("address")
            if contract and Web3.is_address(contract):
                found.append(Token(contract, str(token.get("symbol") or "?"), int(token.get("decimals") or 18)))
        return found


class OnchainSource:
    def __init__(self, web3_factory=web3_for_chain, indexer=None, known_tokens=None):
        self.web3_factory = web3_factory
        self.indexer = indexer or BlockscoutIndexer()
        self.known_tokens = known_tokens or {}

    def assets(self, address: str, chain_id: int) -> AssetSnapshot:
        if chain_id not in RPC_URLS:
            raise ValueError("仅支持 Ethereum 与 BNB Smart Chain")
        address = validate_address(address)
        web3 = self.web3_factory(chain_id)
        observed_at = datetime.now(timezone.utc)
        symbol = "ETH" if chain_id == 1 else "BNB"
        native = Decimal(web3.eth.get_balance(address)) / Decimal(10**18)
        items = [AssetBalance("onchain", chain_id, None, symbol, native, observed_at)]
        tokens = {token.contract.lower(): token for token in self.known_tokens.get(chain_id, [])}
        discovery_complete = True
        error = None
        try:
            for token in self.indexer.discover(address, chain_id):
                tokens.setdefault(token.contract.lower(), token)
        except Exception as exc:
            discovery_complete = False
            error = f"代币发现不完整: {exc}"
        for contract, token in tokens.items():
            if not Web3.is_address(token.contract) or not 0 <= token.decimals <= 36:
                continue
            instance = web3.eth.contract(address=Web3.to_checksum_address(token.contract), abi=ERC20_ABI)
            raw = instance.functions.balanceOf(address).call()
            quantity = Decimal(raw) / Decimal(10**token.decimals)
            if quantity:
                items.append(AssetBalance("onchain", chain_id, contract, token.symbol, quantity, observed_at))
        return AssetSnapshot(items, observed_at, discovery_complete, error)
