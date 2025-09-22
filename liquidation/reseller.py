import datetime
import logging
import time
from datetime import timedelta
from decimal import Decimal

from afp import Trading, bindings
from afp.bindings.erc20 import ERC20
from afp.schemas import Order
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3

from .model import Position

logger = logging.getLogger(__name__)


class Reseller:
    """
    Service for managing and selling positions from multiple margin account contracts.

    The Reseller class aggregates positions from specified margin account contracts,
    validates them, and automates the process of selling these positions
    using the exchange Trading interface. It also manages submitted orders
    and ensures they are filled or cancelled within a specified time window.
    """

    w3: Web3
    margin_accounts: list[ChecksumAddress]
    positions: list[Position]
    orders: list[Order]
    trading: Trading

    def __init__(
        self, w3: Web3, trading: Trading, margin_accounts: list[ChecksumAddress]
    ):
        """
        Initialize the Reseller.

        Args:
            w3 (Web3): Web3 instance for blockchain interaction.
            trading (Trading): Trading interface for submitting orders.
            margin_accounts (list[ChecksumAddress]): List of margin account contract addresses to manage.
        """
        self.w3 = w3
        self.margin_accounts = margin_accounts
        self.positions = []
        self.orders = []
        self.trading = trading

    def populate(self) -> None:
        """
        Populate the reseller cache with positions from all margin accounts.

        Iterates through each margin account, retrieves all positions,
        and stores them in the reseller's position list.
        """
        for margin_account_address in self.margin_accounts:
            margin_account = bindings.MarginAccount(self.w3, margin_account_address)
            decimals = ERC20(self.w3, margin_account.collateral_asset()).decimals()
            positions = margin_account.positions(self.w3.eth.default_account)
            clearing = bindings.ClearingDiamond(self.w3)
            product_registry = bindings.ProductRegistry(self.w3)
            for position in positions:
                position_data = margin_account.position_data(self.w3.eth.default_account, position)
                mark_price = clearing.valuation(position)
                tick_size = product_registry.tick_size(position)
                point_value = Decimal(product_registry.point_value(position))/Decimal(10**decimals)
                self.positions.append(Position(position_data, mark_price, tick_size, point_value))
        logger.info(
            "Populated reseller with %d positions from %d margin accounts.",
            len(self.positions),
            len(self.margin_accounts),
        )

    def validate_position(self, position_id: HexBytes) -> bool:
        """
        Validate if a position is valid and can be sold. This checks if the product is listed on the exchange.

        Args:
            position_id (HexBytes): The position identifier.

        Returns:
            bool: True if the position is valid and can be sold, False otherwise.
        """
        try:
            product = self.trading.product(position_id.to_0x_hex())
            if product is None:
                logger.error("Product with ID %s not found.", position_id.to_0x_hex())
                return False
            return True
        except Exception as e:
            logger.error("Failed to validate position %s: %s", position_id.to_0x_hex(), e)
            return False

    def sell(self) -> None:
        """
        Sell all positions held by the reseller at mark price.

        For each position, creates and submits a limit order using the Trading interface.
        Stores the resulting orders for later tracking.
        """
        if len(self.positions) == 0:
            return
        for position in self.positions:
            try:
                product = self.trading.product(position.position_id.to_0x_hex())
            except Exception as e:
                logger.error(
                    "Failed to retrieve product for position %s: %s",
                    position.position_id,
                    e,
                )
                continue
            side = "ask" if position.quantity > 0 else "bid"
            good_until_time = datetime.datetime.fromtimestamp(
                self.w3.eth.get_block("latest")["timestamp"]
            ) + datetime.timedelta(minutes=5)
            limit_price = Decimal(position.mark_price) / Decimal(10**position.tick_size)
            quantity = abs(position.quantity)
            logger.info(
                "Preparing to close\n\tposition %s\n\tproduct %s\n\tside %s\n\tlimit price %s\n\tquantity %s",
                position.position_id.to_0x_hex(),
                product.id,
                side,
                limit_price,
                quantity,
            )
            intent = self.trading.create_intent(
                product=product,
                side=side,
                limit_price=limit_price,
                quantity=quantity,
                max_trading_fee_rate=Decimal(0.01),  # Example max trading fee rate
                good_until_time=good_until_time,
            )
            logger.info(
                "Created intent with hash: %s, margin account: %s, intent account: %s",
                intent.hash,
                intent.margin_account_id,
                intent.intent_account_id,
            )
            order = self.trading.submit_limit_order(intent)
            logger.info(
                "Submitted order with id: %s type: %s, product: %s, quantity: %s, price: %s, side: %s",
                order.id,
                order.type,
                product.id,
                quantity,
                intent.data.limit_price,
                side,
            )
            self.orders.append(order)