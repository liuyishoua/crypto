from decimal import Decimal

import pytest

from crypto_app.onchain import OnchainSource, Token, validate_address


ADDRESS = "0x000000000000000000000000000000000000dEaD"
TOKEN_A = "0x0000000000000000000000000000000000000001"
TOKEN_B = "0x0000000000000000000000000000000000000002"


class ContractFunctions:
    def __init__(self, raw):
        self.raw = raw

    def balanceOf(self, address):
        return self

    def call(self):
        return self.raw


class Chain:
    def __init__(self, chain_id):
        self.chain_id = chain_id
        self.eth = self

    def get_balance(self, address):
        return 10**18

    def contract(self, address, abi):
        class Contract:
            functions = ContractFunctions(2_500_000)
        return Contract()


class Indexer:
    def __init__(self):
        self.fail = False

    def discover(self, address, chain_id):
        if self.fail:
            raise OSError("indexer offline")
        return [Token(TOKEN_A, "USDC", 6), Token(TOKEN_B, "USDC", 6)]


def test_discovers_and_deduplicates_per_chain():
    indexer = Indexer()
    source = OnchainSource(lambda chain_id: Chain(chain_id), indexer, {1: [Token(TOKEN_A, "USDC", 6)], 56: [Token(TOKEN_A, "USDC", 6)]})
    ethereum = source.assets(ADDRESS, 1)
    bsc = source.assets(ADDRESS, 56)
    assert ethereum.discovery_complete
    assert [(item.chain_id, item.contract, item.quantity) for item in ethereum.items] == [
        (1, None, Decimal(1)), (1, TOKEN_A.lower(), Decimal("2.5")), (1, TOKEN_B.lower(), Decimal("2.5"))
    ]
    assert bsc.items[1].chain_id == 56
    assert ethereum.items[1].symbol == bsc.items[1].symbol


def test_indexer_failure_keeps_known_balances_and_warning():
    indexer = Indexer()
    indexer.fail = True
    source = OnchainSource(lambda chain_id: Chain(chain_id), indexer, {1: [Token(TOKEN_A, "USDC", 6)]})
    snapshot = source.assets(ADDRESS, 1)
    assert not snapshot.discovery_complete
    assert "offline" in snapshot.error
    assert len(snapshot.items) == 2


def test_indexer_failure_preserves_last_complete_discovery_time():
    indexer = Indexer()
    source = OnchainSource(lambda chain_id: Chain(chain_id), indexer, {})
    first = source.assets(ADDRESS, 1)
    indexer.fail = True
    source.assets(ADDRESS, 1)
    assert source.last_success[(ADDRESS, 1)] == first.observed_at


def test_bad_token_does_not_hide_native_balance():
    class BrokenChain(Chain):
        def contract(self, address, abi): raise OSError("token RPC failed")

    source = OnchainSource(lambda chain_id: BrokenChain(chain_id), Indexer(), {})
    snapshot = source.assets(ADDRESS, 1)
    assert snapshot.items[0].symbol == "ETH"
    assert not snapshot.discovery_complete
    assert "token RPC failed" in snapshot.error


def test_rejects_bad_address_and_chain():
    with pytest.raises(ValueError):
        validate_address("0x123")
    with pytest.raises(ValueError):
        OnchainSource(lambda chain_id: Chain(chain_id), Indexer(), {}).assets(ADDRESS, 137)
