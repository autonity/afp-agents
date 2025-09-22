import logging
import os
from datetime import timedelta
from decimal import Decimal
from typing import cast

from afp import Trading, bindings
from eth_account.account import Account
from web3 import HTTPProvider, Web3
from web3.middleware import Middleware, SignAndSendRawMiddlewareBuilder

import notifications
from notifications import get_notifier
from subquery.client import AutSubquery
from utils import format_int, wait_for_blocks

from .bid import FullLiquidationPercentMAEStrategy
from .reseller import Reseller
from .service import LiquidationService

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

notifier = get_notifier()

PRIVATE_KEY = os.environ["PRIVATE_KEY"]
RPC_URL = os.environ["RPC_URL"]
SUBQUERY_URL = os.environ["SUBQUERY_URL"]

# This implies we take 1% of the MAE when liquidating
DMAE = Decimal("0.01")


def main():
    sq = AutSubquery(url=SUBQUERY_URL)
    w3 = Web3(HTTPProvider(RPC_URL))
    signer = Account.from_key(PRIVATE_KEY)
    w3.eth.default_account = signer.address
    signing_middleware = SignAndSendRawMiddlewareBuilder.build(signer)
    w3.middleware_onion.add(cast(Middleware, signing_middleware))

    service = LiquidationService(w3, sq)
    accounts = service.liquidatable_accounts()
    trading = Trading(PRIVATE_KEY)
    reseller = Reseller(
        w3,
        trading,
        sq.margin_accounts(),
    )
    strategy = FullLiquidationPercentMAEStrategy(DMAE, reseller.validate_position)

    logger.info("Found %d liquidatable accounts", len(accounts))
    for account in accounts:
        logger.info("%s - processing Liquidation", account.account_id)
        account.populate()
        logger.info(
            "%s - number of positions %d", account.account_id, len(account.positions)
        )

        liquidation_started, dmae, dmmu = account.start_liquidation(strategy)
        if liquidation_started:
            logger.info("%s - requested liquidation", account.account_id)
        else:
            logger.info("%s - liquidation already in progress", account.account_id)

        current_block = w3.eth.get_block("latest")["number"]
        logger.info(
            "%s - auction started at %s, duration %s, current block %s",
            account.account_id,
            account.auction_data.start_block,
            account.auction_duration,
            current_block,
        )
        ## Here we assume we are liquidating the full MMU
        logger.info(
            "%s - liquidating\n\tMMU: %s,\tMAE: %s\n\tMMU Now: %s,\tMAE Now: %s",
            account.account_id,
            format_int(account.auction_data.mmu_at_initiation, account.collateral_decimals),
            format_int(account.auction_data.mae_at_initiation, account.collateral_decimals),
            format_int(account.auction_data.mmu_now, account.collateral_decimals),
            format_int(account.auction_data.mae_now, account.collateral_decimals),
        )
        clearing = bindings.ClearingDiamond(w3)
        mae_offered = clearing.max_mae_offered(
            account.account_id, account.collateral_asset, account.auction_data.mmu_now
        )
        logger.info(
            "%s - max MAE offered: %s",
            account.account_id,
            format_int(mae_offered, account.collateral_decimals),
        )
        bids = FullLiquidationPercentMAEStrategy(
            DMAE, reseller.validate_position
        ).construct_bids(account.positions)
        mae_check_failed, mae_over_mmu_exceeded = clearing.mae_check_on_bid(
            w3.eth.default_account,
            account.account_id,
            account.collateral_asset,
            bids,
        )
        if mae_check_failed or mae_over_mmu_exceeded:
            logger.info(
                "%s - MAE check failed: %s, MAE over MMU exceeded: %s",
                account.account_id,
                mae_check_failed,
                mae_over_mmu_exceeded,
            )
            continue
        blocks_to_wait = account.wait_time_for(dmae, dmmu)
        logger.info(
            "%s - waiting for %s before liquidation",
            account.account_id,
            blocks_to_wait,
        )
        ## wait an extra block to ensure we are clear
        wait_for_blocks(w3, blocks_to_wait + 1)
        account.bid_liquidation(strategy)

    if len(accounts) > 0:
        content = f"Liquidation processed for {len(accounts)} margin accounts"
        notify_data = [
            notifications.NotificationItem(
                title=f"Account {account.account_id} liquidated",
                values={
                    "Account ID": account.account_id,
                    "Collateral Asset": account.collateral_asset,
                    "MMU (before)": Decimal(account.auction_data.mae_at_initiation) / Decimal(10**account.collateral_decimals),
                    "MAE (before)": Decimal(account.auction_data.mae_at_initiation) / Decimal(10**account.collateral_decimals),
                    "Positions": str(len(account.positions)),
                },
            )
            for account in accounts
        ]
        notifier.notify(
            "Margin Accounts Liquidated",
            content,
            notify_data,
        )

    logger.info("Liquidation bids submitted for %d margin accounts", len(accounts))
    # Here we check all margin accounts for positions, just in case some accounts were not liquidated
    # in previous runs
    reseller.populate()
    reseller.sell()
    logger.info(
        "Reseller selling all positions for %d margin accounts",
        len(reseller.margin_accounts),
    )
    logger.info("Orders submitted: %d", len(reseller.orders))

if __name__ == "__main__":
    main()
