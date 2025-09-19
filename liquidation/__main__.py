import logging
import os
from datetime import timedelta
from decimal import Decimal
from typing import cast

from afp import Trading, bindings
from eth_account.account import Account
from web3 import HTTPProvider, Web3
from web3.middleware import Middleware, SignAndSendRawMiddlewareBuilder

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

PRIVATE_KEY = os.environ["PRIVATE_KEY"]
RPC_URL = os.environ["RPC_URL"]
SUBQUERY_URL = os.environ["SUBQUERY_URL"]

# This implies we take 10% of the MAE when liquidating
DMAE = Decimal("0.1")

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

    logger.info("Found %d liquidatable accounts", len(accounts))
    for account in accounts:
        logger.info("%s - processing Liquidation", account.account_id)
        account.populate()
        logger.info("%s - number of positions %d", account.account_id, len(account.positions))

        if account.start_liquidation():
            logger.info("%s - requested liquidation", account.account_id)
        else:
            logger.info("%s - liquidation already in progress", account.account_id)

        current_block = w3.eth.get_block('latest')["number"]
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
            format_int(account.auction_data.mmu_at_initiation, 18),
            format_int(account.auction_data.mae_at_initiation, 18),
            format_int(account.auction_data.mmu_now, 18),
            format_int(account.auction_data.mae_now, 18),
        )
        clearing = bindings.ClearingDiamond(w3)
        mae_offered = clearing.max_mae_offered(account.account_id, account.collateral_asset, account.auction_data.mmu_now)
        logger.info(
            "%s - max MAE offered: %s",
            account.account_id,
            format_int(mae_offered, 18),
        )
        bids = FullLiquidationPercentMAEStrategy(DMAE, reseller.validate_position).construct_bids(account.positions)
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
        blocks_to_wait = account.wait_time_for(DMAE, Decimal("1.0"))
        logger.info(
            "%s - waiting for %s before liquidation",
            account.account_id,
            blocks_to_wait,
        )
        wait_for_blocks(w3, blocks_to_wait)
        account.bid_liquidation(FullLiquidationPercentMAEStrategy(DMAE, reseller.validate_position))

    logger.info("Liquidation bids submitted for %d margin accounts", len(accounts))
    # Here we check all margin accounts for positions, just in case some accounts were not liquidated
    # in previous runs
    reseller.populate()
    reseller.sell()
    logger.info("Reseller sold all positions for %d margin accounts", len(reseller.margin_accounts))
    logger.info("Orders submitted: %d", len(reseller.orders))
    reseller.wait_for_orders(timedelta(minutes=1), timedelta(seconds=1))

if __name__ == "__main__":
    main()
