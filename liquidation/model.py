from decimal import Decimal
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
    point_value: Decimal

    def __init__(
        self, position_data: afp.bindings.PositionData, mark_price: int, tick_size: int, point_value: Decimal
    ):
        super().__init__(**vars(position_data))
        self.mark_price = mark_price
        self.tick_size = tick_size
        self.point_value = point_value

    def notional_at_mark(self) -> Decimal:
        return Decimal(self.mark_price * abs(self.quantity) * self.point_value) / Decimal(10**self.tick_size)

    def notional_at_price(self, price: int) -> Decimal:
        return Decimal(price * abs(self.quantity) * self.point_value) / Decimal(10**self.tick_size)

    # Returns the amount of MAE (without the collateral token precision) decreased with this `bid_price`
    def dmae(self, bid_price: int) -> Decimal:
        return (
            self.notional_at_mark() - self.notional_at_price(bid_price) if self.quantity > 0
            else self.notional_at_price(bid_price) - self.notional_at_mark()
        )
