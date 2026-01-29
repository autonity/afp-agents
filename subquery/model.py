from dataclasses import dataclass
from eth_typing import ChecksumAddress


@dataclass(frozen=True)
class AccountInfo:
    account: ChecksumAddress
    margin_account_address: ChecksumAddress
    quantity: int


@dataclass(frozen=True)
class ProductInfo:
    id: str
    name: str
    state: str
    earliest_fsp_submission_time: int
    tradeout_interval: int
    fsp: int