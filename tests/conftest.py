import os
import time
from typing import List, Tuple
from unittest.mock import patch

import pytest
from afp.bindings import AuctionConfig
from eth_typing import ChecksumAddress
from eth_utils import to_checksum_address
from hexbytes import HexBytes

from subquery.model import Account, ProductInfo


def random_address() -> ChecksumAddress:
    """Generate a random Ethereum address."""
    random_bytes = os.urandom(20)  # Generate 20 random bytes
    hex_addr = "0x" + random_bytes.hex()  # Convert to hex format
    return to_checksum_address(hex_addr)  # Convert to ChecksumAddress format


def random_active_accounts() -> Tuple[List[Account], List[ChecksumAddress]]:
    """Generate a list of random active accounts."""
    margin_account = random_address()
    collateral_asset = random_address()
    accounts = [
        Account(
            account_id=random_address(),
            margin_account=margin_account,
            collateral_asset=collateral_asset,
        )
        for _ in range(5)  # Generate 5 random accounts
    ]
    products = [
        random_address() for _ in range(3)
    ]  # Generate 3 random product addresses
    return accounts, products


TEST_ACCOUNTS: Tuple[List[Account], List[ChecksumAddress]] = random_active_accounts()


@pytest.fixture
def autsubquery_mock():
    with patch("subquery.client.AutSubquery") as mock:
        mock.active_accounts.return_value = TEST_ACCOUNTS
        mock.products.return_value = TEST_ACCOUNTS[1]
        yield mock


@pytest.fixture
def clearing_mock():
    with patch("afp.bindings.ClearingDiamond") as mock:
        mock.return_value.auction_config.return_value = AuctionConfig(
            liquidation_duration=100,
            restoration_buffer=10,
        )
        yield mock


@pytest.fixture
def w3_mock():
    with patch("web3.Web3") as mock:
        mock.return_value.is_connected.return_value = True
        yield mock

@pytest.fixture
def margin_account_mock():
    with patch("afp.bindings.MarginAccount") as mock:
        yield mock

def random_id() -> HexBytes:
    """Generate a random HexBytes ID."""
    random_bytes = os.urandom(32)  # Generate 32 random bytes
    return HexBytes(random_bytes)  # Convert to HexBytes format


def random_products_with_fsp_passed(n=3, tradeout_interval=600) -> List[ProductInfo]:
    """Generate a list of random products with FSP passed."""
    products = [
        ProductInfo(
            id=random_id().to_0x_hex(),
            name=f"Product {i}",
            state="3",
            earliestFSPSubmissionTime=int(time.time()) - 1000,
            tradeoutInterval=tradeout_interval,  # Example interval
            fsp=1,  # Example FSP value
        )
        for i in range(n)  # Generate 3 random products
    ]
    return products
