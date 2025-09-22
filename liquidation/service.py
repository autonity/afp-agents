import logging
import math
from decimal import Decimal
from typing import Tuple

import afp.bindings
from afp.bindings.erc20 import ERC20
from eth_typing import ChecksumAddress
from web3 import Web3

import subquery.model
from subquery.client import AutSubquery

from .bid import BidStrategy
from .model import Position, Step, TransactionStep

logger = logging.getLogger(__name__)

MAX_ACCOUNT_FETCH = 50


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
    collateral_decimals: int | None
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
        decimals = ERC20(self.w3, self.collateral_asset).decimals()
        positions = margin_account.positions(self.account_id)
        clearing = afp.bindings.ClearingDiamond(self.w3)
        product_registry = afp.bindings.ProductRegistry(self.w3)
        for position in positions:
            position_data = margin_account.position_data(self.account_id, position)
            mark_price = clearing.valuation(position)
            tick_size = product_registry.tick_size(position)
            point_value = Decimal(product_registry.point_value(position)) / Decimal(
                10**decimals
            )
            self.positions.append(
                Position(position_data, mark_price, tick_size, point_value)
            )
        clearing = afp.bindings.ClearingDiamond(self.w3)
        self.is_liquidating = clearing.is_liquidating(
            self.account_id, self.collateral_asset
        )
        if self.is_liquidating:
            self.auction_data = clearing.auction_data(
                self.account_id, self.collateral_asset
            )
        self.collateral_decimals = decimals

    def is_transaction_submitted(self, step: Step) -> bool:
        """
        Check if a transaction step is already submitted.

        Args:
            step (Step): The transaction step to check.

        Returns:
            bool: True if the step has already been submitted, False otherwise.
        """
        return any(submitted.step == step for submitted in self.transaction_steps)

    def start_liquidation(self, strategy: BidStrategy) -> (bool, Decimal, Decimal):
        """
        Initiate liquidation for the account if not already in progress.

        Returns:
            bool: True if liquidation was started, False otherwise.
            Decimal: Mae delta after bid
            Decimal: Mmu delta after bid
        """
        dmae, dmmu = self._check_bids(strategy.construct_bids(self.positions))
        if self.is_liquidating:
            # ( bool, (Decimal, Decimal))
            return False, dmae, dmmu
        if self.is_transaction_submitted(Step.REQUEST_LIQUIDATION):
            logger.info("%s - liquidation already requested", self.account_id)
            return False, dmae, dmmu
        clearing = afp.bindings.ClearingDiamond(self.w3)
        fn = clearing.request_liquidation(self.account_id, self.collateral_asset)
        tx_hash = fn.transact()
        self.transaction_steps.append(
            TransactionStep(Step.REQUEST_LIQUIDATION, tx_hash)
        )
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        self.is_liquidating = True
        self.auction_data = clearing.auction_data(
            self.account_id, self.collateral_asset
        )
        return True, dmae, dmmu

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
            logger.info(
                "%s - no valid bids constructed, skipping liquidation", self.account_id
            )
            return False
        self._check_bids(bids)
        fn = clearing.bid_auction(self.account_id, self.collateral_asset, bids)
        tx_hash = fn.transact()
        logger.info(
            "%s - bidding on liquidation auction with tx %s",
            self.account_id,
            tx_hash.hex(),
        )
        self.transaction_steps.append(TransactionStep(Step.BID_AUCTION, tx_hash))
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logging.info(
            "%s - liquidation tx mined in block %d",
            self.account_id,
            receipt["blockNumber"],
        )
        logger.info("%s - liquidation processed", self.account_id)
        return True

    def _check_bids(self, bids: list[afp.bindings.BidData]) -> (Decimal, Decimal):
        margin_account = afp.bindings.MarginAccount(self.w3, self.margin_account)
        mae_before, mmu_before = (
            margin_account.mae(self.account_id),
            margin_account.mmu(self.account_id),
        )
        settlements: list[afp.bindings.Settlement] = []
        for bid in bids:
            settlements.append(
                afp.bindings.Settlement(
                    position_id=bid.product_id,
                    quantity=-bid.quantity
                    if bid.side == afp.bindings.Side.BID
                    else bid.quantity,
                    price=bid.price,
                )
            )
        mark_prices = afp.bindings.SystemViewer(self.w3).valuations(
            [bid.product_id for bid in bids]
        )
        mae_after, mmu_after = margin_account.mae_and_mmu_after_batch_trade(
            self.account_id, settlements, mark_prices
        )
        dmae, dmmu = (
            Decimal(mae_before - mae_after) / Decimal(10**self.collateral_decimals),
            Decimal(mmu_before - mmu_after) / Decimal(10**self.collateral_decimals),
        )
        logger.info(
            "%s - MAE after bid: %s, MMU after bid: %s",
            self.account_id,
            f"{Decimal(mae_after) / Decimal(10**self.collateral_decimals):,.2f}",
            f"{Decimal(mmu_after) / Decimal(10**self.collateral_decimals):,.2f}",
        )
        if dmae < Decimal(0):
            raise RuntimeError("MAE did not decrease after bid")
        if dmmu < Decimal(0):
            raise RuntimeError("MMU did not decrease after bid")
        return dmae, dmmu

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
        current_block = self.w3.eth.get_block("latest")["number"]
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
        account_details = self.fetch_account_details(accounts)

        logger.info("Found %d active accounts", len(accounts))
        liquidatable_accounts = []
        for acct, details in account_details:
            token = ERC20(self.w3, acct.collateral_asset)
            decimals = token.decimals()
            logger.info("Checking account %s", acct.account_id)
            mae = details.mae
            mmu = details.mmu
            if mae >= mmu:
                logger.info(
                    "Account %s not liquidatable: MAE %s >= MMU %s",
                    acct.account_id,
                    f"{Decimal(mae) / Decimal(10**decimals):,.2f}",
                    f"{Decimal(mmu) / Decimal(10**decimals):,.2f}",
                )
                continue

            logger.info("Found liquidatable account %s", acct.account_id)
            logger.info(
                "Account (%s)\n\tMAE: %s\n\tMMU %s",
                acct.account_id,
                f"{Decimal(mae) / Decimal(10**decimals):,.2f}",
                f"{Decimal(mmu) / Decimal(10**decimals):,.2f}",
            )

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

    def fetch_account_details(
        self, accounts: list[subquery.model.Account]
    ) -> list[Tuple[subquery.model.Account, afp.bindings.UserMarginAccountData]]:
        result = []
        system_viewer = afp.bindings.SystemViewer(self.w3)
        grouped = group_by_collateral(accounts)
        for collateral, accounts in grouped.items():
            account_data = []
            for i in range(0, len(accounts), MAX_ACCOUNT_FETCH):
                batch = accounts[i : i + MAX_ACCOUNT_FETCH]
                account_data.extend(
                    system_viewer.user_margin_data_by_collateral_asset(
                        collateral, [item.account_id for item in batch]
                    )
                )
            result.extend(zip(accounts, account_data))
        return result

    def auction_config(self) -> tuple[int, Decimal]:
        """
        Retrieve the auction configuration parameters.

        Returns:
            tuple[int, Decimal]: Duration of the liquidation period and restoration buffer.
        """
        if (
            self.liquidation_duration is not None
            and self.restoration_buffer is not None
        ):
            return self.liquidation_duration, self.restoration_buffer

        clearing = afp.bindings.ClearingDiamond(self.w3)
        cfg = clearing.auction_config()
        self.liquidation_duration = cfg.liquidation_duration
        self.restoration_buffer = Decimal(cfg.restoration_buffer) / Decimal(10**4)

        return self.liquidation_duration, self.restoration_buffer


def group_by_collateral(
    accounts: list[subquery.model.Account],
) -> dict[ChecksumAddress, list[subquery.model.Account]]:
    result: dict[ChecksumAddress, list[subquery.model.Account]] = {}
    for acct in accounts:
        if acct.collateral_asset not in result:
            result[acct.collateral_asset] = []
        result[acct.collateral_asset].append(acct)
    return result
