from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Callable

import afp.bindings
from hexbytes import HexBytes

from utils import parse_decimal

from .model import Position


class BidStrategy(ABC):
    """
    Abstract base class for liquidation bid strategies.

    Subclasses must implement the construct_bids method to generate bids for a set of positions.
    """

    @abstractmethod
    def construct_bids(self, positions: list[Position]) -> list[afp.bindings.BidData]:
        """
        Construct bids for the liquidating account based on its positions.

        Args:
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            list[afp.bindings.BidData]: List of bid data objects.
        """
        pass


class FullLiquidationMarkPriceStrategy(BidStrategy):
    """
    Liquidate all positions at their mark price.

    This strategy creates bids for every position held by the liquidating account at the mark price,
    without affecting the MAE of the liquidating account.
    """

    def __init__(self, position_validator: Callable[[HexBytes], bool]):
        """
        Args:
            position_validator (Callable[[HexBytes], bool]): Function to validate if a position can be liquidated.
        """
        self.position_validator = position_validator

    def construct_bids(self, positions: list[Position]) -> list[afp.bindings.BidData]:
        """
        Construct bids for every position held by the liquidating account at the mark price.

        Args:
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            list[afp.bindings.BidData]: List of bid data objects.
        """
        bids = []
        for position in positions:
            if not self.position_validator(position.position_id):
                continue
            mark_price = position.mark_price
            quantity = -position.quantity
            side = afp.bindings.Side.BID if quantity < 0 else afp.bindings.Side.ASK
            bids.append(afp.bindings.BidData(
                product_id=position.position_id,
                quantity=abs(quantity),
                price=mark_price,
                side=side,
            ))
        return bids


class FullLiquidationPercentMAEStrategy(BidStrategy):
    """
    Liquidate all positions at a percentage of MAE.

    This strategy creates bids for full liquidation based on a percentage of the mark price,
    reducing the MAE of the liquidating account by percent_mae.
    """

    def __init__(self, percent_mae: Decimal, position_validator: Callable[[HexBytes], bool]):
        """
        Args:
            percent_mae (Decimal): Percentage of MAE to use for bid price adjustment.
            position_validator (Callable[[HexBytes], bool]): Function to validate if a position can be liquidated.
        """
        self.percent_mae = percent_mae
        self.position_validator = position_validator

    def construct_bids(self, positions: list[Position]) -> list[afp.bindings.BidData]:
        """
        Construct bids for full liquidation based on a percentage of the mark price.

        Args:
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            list[afp.bindings.BidData]: List of bid data objects.
        """
        bids = []
        for position in positions:
            if not self.position_validator(position.position_id):
                continue
            mark_price = Decimal(position.mark_price) / Decimal(10 ** position.tick_size)
            tick_size = position.tick_size
            quantity = -position.quantity
            side = afp.bindings.Side.BID if quantity < 0 else afp.bindings.Side.ASK
            bid_price = mark_price * (1 - self.percent_mae) if quantity > 0 else mark_price * (1 + self.percent_mae)
            bids.append(afp.bindings.BidData(
                product_id=position.position_id,
                quantity=abs(quantity),
                price=parse_decimal(bid_price, tick_size),
                side=side,
            ))
        return bids


class OrderedPercentMAEStrategy(BidStrategy):
    """Liquidate largest positions first at a percentage of MAE."""

    def __init__(self, percent_mae: Decimal):
        self.percent_mae = percent_mae

    def construct_bids(self, positions: list[Position]) -> list[afp.bindings.BidData]:
        # ToDo: bid the largest positions
        raise NotImplementedError("OrderedPercentMAEStrategy not implemented yet.")
