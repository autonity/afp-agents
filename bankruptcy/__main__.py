import logging
import os
from typing import cast

from eth_account.account import Account
from web3 import HTTPProvider, Web3
from web3.middleware import Middleware, SignAndSendRawMiddlewareBuilder

from subquery.client import AutSubquery

from .service import BankruptcyService

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

PRIVATE_KEY = os.environ["PRIVATE_KEY"]
RPC_URL = os.environ["RPC_URL"]
SUBQUERY_URL = os.environ["SUBQUERY_URL"]


def main():
    sq = AutSubquery(url=SUBQUERY_URL)
    w3 = Web3(HTTPProvider(RPC_URL))
    signer = Account.from_key(PRIVATE_KEY)
    w3.eth.default_account = signer.address
    signing_middleware = SignAndSendRawMiddlewareBuilder.build(signer)
    w3.middleware_onion.add(cast(Middleware, signing_middleware))

    service = BankruptcyService(w3, sq)
    accounts = service.bankrupt_accounts()

    logger.info("Found %d bankrupt accounts", len(accounts))
    for account in accounts:
        logger.info("%s - processing bankruptcy", account.account_id)
        account.populate()
        logger.info(
            "%s - number of positions %d", account.account_id, len(account.positions)
        )

        tx = account.start_loss_mutualization()
        logger.info(
            "%s - loss mutualization triggered, current block %s",
            account.account_id,
            w3.eth.get_block("latest")["number"],
        )
        ## Here we assume we are liquidating the full MMU
        receipt = w3.eth.wait_for_transaction_receipt(tx)
        logger.info(
            "%s - loss mutualization completed in block %d",
            account.account_id,
            receipt.blockNumber,
        )
    logger.info("Bankruptcy submitted for %d margin accounts", len(accounts))


if __name__ == "__main__":
    main()
