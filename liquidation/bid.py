from abc import ABC, abstractmethod
from decimal import Decimal
import math
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
    def construct_bids(self, mae_initial: int, positions: list[Position]) -> (bool, list[afp.bindings.BidData]):
        """
        Construct bids for the liquidating account based on its positions.

        Args:
            mae_initial (int): Initial MAE of the account
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            bool: True if bid construction is possible, False otherwise
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

    def construct_bids(self, mae_initial: int, positions: list[Position]) -> (bool, list[afp.bindings.BidData]):
        """
        Construct bids for every position held by the liquidating account at the mark price.

        Args:
            mae_initial (int): Initial MAE of the account
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            bool: True if bid construction is possible, False otherwise
            list[afp.bindings.BidData]: List of bid data objects.
        """
        bids = []
        for position in positions:
            if not self.position_validator(position.position_id):
                continue
            mark_price = position.mark_price
            quantity = position.quantity
            side = afp.bindings.Side.BID if quantity > 0 else afp.bindings.Side.ASK
            bids.append(
                afp.bindings.BidData(
                    product_id=position.position_id,
                    quantity=abs(quantity),
                    price=mark_price,
                    side=side,
                )
            )
        return True, bids


class FullLiquidationPercentMAEStrategy(BidStrategy):
    """
    Liquidate all positions at a percentage of MAE.

    This strategy creates bids for full liquidation based on a percentage of the mark price,
    reducing the MAE of the liquidating account by percent_mae.
    """

    percent_mae: Decimal

    def __init__(
        self, percent_mae: Decimal, position_validator: Callable[[HexBytes], bool]
    ):
        """
        Args:
            percent_mae (Decimal): Percentage of MAE to use for bid price adjustment.
            position_validator (Callable[[HexBytes], bool]): Function to validate if a position can be liquidated.
        """
        self.percent_mae = percent_mae
        self.position_validator = position_validator

    def construct_bids(self, mae_initial: int, positions: list[Position]) -> (bool, list[afp.bindings.BidData]):
        """
        Construct bids for full liquidation based on a percentage of the mark price.

        Args:
            mae_initial (int): Initial MAE of the account
            positions (list[Position]): List of positions to construct bids for.

        Returns:
            bool: True if bid construction is possible, False otherwise
            list[afp.bindings.BidData]: List of bid data objects.
        """
        bids = []
        skip_bids = []
        sum_notional_long = Decimal(0)
        sum_notional_short = Decimal(0)
        for position in positions:
            if not self.position_validator(position.position_id):
                skip_bids.append(True)
                continue
            if position.mark_price == 0:
                # just a safety check for further calculation
                raise RuntimeError("Got zero mark price for position ", position.position_id)

            if position.quantity > 0:
                sum_notional_long += position.notional_at_mark()
            else:
                sum_notional_short += position.notional_at_mark()

            skip_bids.append(False)

        # we calculate a constant difference percentage between mark price and bid price for all positions
        # so that we take `mae_initial * percent_mae` amount of MAE from the liquidating account
        #
        # the condition we assumed here is the following:
        # `percent_dmark_long * sum_notional_long + percent_dmark_short * sum_notional_short >= dmae`
        # we solve this assuming `percent_dmark_long = percent_dmark_short = percent_dmark`
        percent_dmark = Decimal(mae_initial) * self.percent_mae / (sum_notional_long + sum_notional_short)
        percent_dmark_long = Decimal(0)
        percent_dmark_short = Decimal(0)
        if percent_dmark > Decimal(1):
            # for long positions, bid price cannot differ more than 100% from mark price
            # we can use different percentage for long and short positions to compensate this
            # we will take 100% different for long, which means the bid price will be zero
            percent_dmark_long = Decimal(1)

            # for short, we will calculate the price different percentage from here
            percent_dmark_short = (Decimal(mae_initial) * self.percent_mae - sum_notional_long) / sum_notional_short
        else:
            percent_dmark_long = percent_dmark
            percent_dmark_short = percent_dmark

        for index, position in enumerate(positions):
            if skip_bids[index]:
                continue
            quantity = position.quantity
            mark_price = position.mark_price
            side = afp.bindings.Side.BID if quantity > 0 else afp.bindings.Side.ASK
            bid_price = (
                math.floor(
                    Decimal(mark_price) * (1 - percent_dmark_long)
                ) if quantity > 0
                else math.ceil(
                    Decimal(mark_price) * (1 + percent_dmark_short)
                )
            )
            bids.append(
                afp.bindings.BidData(
                    product_id=position.position_id,
                    quantity=abs(quantity),
                    price=bid_price,
                    side=side,
                )
            )
        return True, bids


class OrderedPercentMAEStrategy(BidStrategy):
    """Liquidate largest positions first at a percentage of MAE."""

    def __init__(self, percent_mae: Decimal):
        self.percent_mae = percent_mae

    def construct_bids(self, mae_initial: int, positions: list[Position]) -> (bool, list[afp.bindings.BidData]):
        # ToDo: bid the largest positions
        raise NotImplementedError("OrderedPercentMAEStrategy not implemented yet.")
