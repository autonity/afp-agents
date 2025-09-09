import logging
import math
import os
from decimal import Decimal

import afp.bindings
from eth_typing import ChecksumAddress
from web3 import Web3

from liquidation.bid import BidStrategy
from liquidation.model import Position, Step, TransactionStep
from subquery.client import AutSubquery

logger = logging.getLogger(__name__)


class LiquidatingAccountContext:
    """
    Context for managing the liquidation process of a single account.

    This class encapsulates the state and operations required to initiate and participate
    in a liquidation auction for a margin account. It tracks positions, auction data,
    transaction steps, and provides methods for starting liquidation, bidding, and
    calculating auction wait times.
    """

    client: AutSubquery
    w3: Web3

    account_id: ChecksumAddress
    collateral_asset: ChecksumAddress
    margin_account: ChecksumAddress
    is_liquidating: bool
    positions: list[Position]
    auction_data: afp.bindings.AuctionData | None
    auction_duration: int
    restoration_buffer: Decimal

    transaction_steps: list[TransactionStep]

    def __init__(
            self,
            w3: Web3,
            account_id: ChecksumAddress,
            collateral_asset: ChecksumAddress,
            margin_account: ChecksumAddress,
            auction_duration: int,
            restoration_buffer: Decimal,
    ):
        """
        Initialize the LiquidatingAccountContext.

        Args:
            w3 (Web3): Web3 instance for blockchain interaction.
            account_id (ChecksumAddress): The account to be liquidated.
            collateral_asset (ChecksumAddress): The collateral asset address.
            margin_account (ChecksumAddress): The margin account contract address.
            auction_duration (int): Duration of the liquidation auction in blocks.
            restoration_buffer (Decimal): Buffer MAE above MMU for a successful bid.
        """
        self.w3 = w3
        self.account_id = account_id
        self.collateral_asset = collateral_asset
        self.margin_account = margin_account
        self.positions = []
        self.auction_duration = auction_duration
        self.restoration_buffer = restoration_buffer
        self.transaction_steps = []

    def populate(self) -> None:
        """
        Populate the context with account positions and auction data.

        Fetches positions, mark prices, tick sizes, and determines if the account
        is currently undergoing liquidation. If so, retrieves auction data.
        """
        margin_account = afp.bindings.MarginAccount(self.w3, self.margin_account)
        positions = margin_account.positions(self.account_id)
        clearing = afp.bindings.ClearingDiamond(self.w3)
        product_registry = afp.bindings.ProductRegistry(self.w3)
        for position in positions:
            position_data = margin_account.position_data(self.account_id, position)
            mark_price = clearing.valuation(position)
            tick_size = product_registry.tick_size(position)
            self.positions.append(Position(position_data, mark_price, tick_size))
        clearing = afp.bindings.ClearingDiamond(self.w3)
        self.is_liquidating = clearing.is_liquidating(self.account_id, self.collateral_asset)
        if self.is_liquidating:
            self.auction_data = clearing.auction_data(self.account_id, self.collateral_asset)

    def is_transaction_submitted(self, step: Step) -> bool:
        """
        Check if a transaction step is already submitted.

        Args:
            step (Step): The transaction step to check.

        Returns:
            bool: True if the step has already been submitted, False otherwise.
        """
        return any(submitted.step == step for submitted in self.transaction_steps)

    def start_liquidation(self) -> bool:
        """
        Initiate liquidation for the account if not already in progress.

        Returns:
            bool: True if liquidation was started, False otherwise.
        """
        if self.is_liquidating:
            return False
        if self.is_transaction_submitted(Step.REQUEST_LIQUIDATION):
            logger.info("%s - liquidation already requested", self.account_id)
            return False
        clearing = afp.bindings.ClearingDiamond(self.w3)
        fn = clearing.request_liquidation(self.account_id, self.collateral_asset)
        tx_hash = fn.transact()
        self.transaction_steps.append(TransactionStep(Step.REQUEST_LIQUIDATION, tx_hash))
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        self.is_liquidating = True
        self.auction_data = clearing.auction_data(self.account_id, self.collateral_asset)
        return True

    def bid_liquidation(self, strategy: BidStrategy) -> bool:
        """
        Submit a bid for the liquidation auction using the provided strategy.

        Args:
            strategy (BidStrategy): Strategy to construct bids.

        Returns:
            bool: True if a bid was submitted, False otherwise.
        """
        if not self.is_liquidating:
            return False
        if self.is_transaction_submitted(Step.BID_AUCTION):
            logger.info("%s - liquidation already in progress", self.account_id)
            return False
        clearing = afp.bindings.ClearingDiamond(self.w3)
        bids = strategy.construct_bids(self.positions)
        if len(bids) == 0:
            logger.info("%s - no valid bids constructed, skipping liquidation", self.account_id)
            return False
        fn = clearing.bid_auction(self.account_id, self.collateral_asset, bids)
        tx_hash = fn.transact()
        logger.info("%s - bidding on liquidation auction with tx %s", self.account_id, tx_hash.hex())
        self.transaction_steps.append(TransactionStep(Step.BID_AUCTION, tx_hash))
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logging.info("%s - liquidation tx mined in block %d", self.account_id, receipt["blockNumber"])
        logger.info("%s - liquidation processed", self.account_id)
        return True

    def wait_time_for(self, dmae: Decimal, dmmu: Decimal) -> int:
        """
        Calculate the remaining wait time for the auction based on delta MAE and delta MMU.

        Args:
            dmae (Decimal): Delta MAE value.
            dmmu (Decimal): Delta MMU value.

        Returns:
            int: Number of blocks left to wait for the auction.
        """
        if self.auction_data is None:
            raise RuntimeError("Call populate() before calculating wait time.")
        current_block = self.w3.eth.get_block('latest')["number"]
        if current_block - self.auction_data.start_block > self.auction_duration:
            # Auction duration has already passed
            return 0
        tau = Decimal(self.auction_duration)
        mmu_0 = Decimal(self.auction_data.mmu_at_initiation)
        mae_0 = Decimal(self.auction_data.mae_at_initiation)
        t = (dmae * tau * mmu_0) / (dmmu * mae_0)
        blocks_to_wait = math.ceil(t)

        # this assumes 1 block per second
        blocks_left = blocks_to_wait - (current_block - self.auction_data.start_block)
        if blocks_left < 0:
            return 0
        return blocks_left


class LiquidationService:
    """
    Service for managing liquidation operations across multiple accounts.

    Provides methods to discover liquidatable accounts, retrieve auction configuration,
    and coordinate the liquidation process using subquery data and blockchain interactions.
    """

    client: AutSubquery
    w3: Web3
    liquidation_duration: int | None
    restoration_buffer: Decimal | None

    def __init__(self, w3: Web3, client: AutSubquery):
        """
        Initialize the LiquidationService.

        Args:
            w3 (Web3): Web3 instance for blockchain interaction.
            client (AutSubquery): Subquery client for querying account data.
        """
        self.client = client
        self.w3 = w3
        self.liquidation_duration = None
        self.restoration_buffer = None

    def liquidatable_accounts(self) -> list[LiquidatingAccountContext]:
        """
        Discover and return all accounts eligible for liquidation.

        Returns:
            list[LiquidatingAccountContext]: List of contexts for liquidatable accounts.
        """
        accounts, _ = self.client.active_accounts()
        clearing = afp.bindings.ClearingDiamond(self.w3)

        logger.info("Found %d active accounts", len(accounts))
        liquidatable_accounts = []
        for acct in accounts:
            logger.info("Checking account %s", acct.account_id)
            if not clearing.is_liquidatable(acct.account_id, acct.collateral_asset):
                logger.info("Account %s is not liquidatable", acct.account_id)
                continue

            logger.info("Found liquidatable account %s", acct.account_id)

            margin_account_contract = afp.bindings.MarginAccount(self.w3, acct.margin_account)
            mae = margin_account_contract.mae(acct.account_id)
            mmu = margin_account_contract.mmu(acct.account_id)
            logger.info("Account (%s)\n\tMAE: %s\n\tMMU %s", acct.account_id, f"{Decimal(mae) / Decimal(10 ** 18):,.2f}",
                        f"{Decimal(mmu) / Decimal(10 ** 18):,.2f}")

            duration, buffer = self.auction_config()
            liquidatable_accounts.append(
                LiquidatingAccountContext(
                    self.w3,
                    acct.account_id,
                    acct.collateral_asset,
                    acct.margin_account,
                    duration,
                    buffer,
                )
            )

        return liquidatable_accounts

    def auction_config(self) -> tuple[int, Decimal]:
        """
        Retrieve the auction configuration parameters.

        Returns:
            tuple[int, Decimal]: Duration of the liquidation period and restoration buffer.
        """
        if self.liquidation_duration is not None and self.restoration_buffer is not None:
            return self.liquidation_duration, self.restoration_buffer

        clearing = afp.bindings.ClearingDiamond(self.w3)
        cfg = clearing.auction_config()
        self.liquidation_duration = cfg.liquidation_duration
        self.restoration_buffer = Decimal(cfg.restoration_buffer) / Decimal(10 ** 4)

        return self.liquidation_duration, self.restoration_buffer
