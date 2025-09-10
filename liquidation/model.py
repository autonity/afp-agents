from enum import Enum

import afp.bindings
from hexbytes import HexBytes


class Step(Enum):
    REQUEST_LIQUIDATION = 1
    BID_AUCTION = 2


class TransactionStep:
    def __init__(self, step: Step, tx_hash: HexBytes):
        self.step = step
        self.tx_hash = tx_hash

    def __repr__(self):
        return f"TransactionStep(step={self.step}, hash={self.tx_hash})"

    def to_dict(self) -> dict:
        return {"step": self.step, "tx_hash": self.tx_hash}


class Position(afp.bindings.PositionData):
    mark_price: int
    tick_size: int

    def __init__(
        self, position_data: afp.bindings.PositionData, mark_price: int, tick_size: int
    ):
        super().__init__(**vars(position_data))
        self.mark_price = mark_price
        self.tick_size = tick_size

