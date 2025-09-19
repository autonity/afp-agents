import logging
import os
from typing import cast

import afp.bindings
from eth_account.account import Account
from web3 import HTTPProvider, Web3
from web3.middleware import Middleware, SignAndSendRawMiddlewareBuilder

import notifications
from notifications import get_notifier
from notifications.utils import format_link
from subquery.client import AutSubquery

from .service import CloseoutService

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

PRIVATE_KEY = os.environ["PRIVATE_KEY"]
RPC_URL = os.environ["RPC_URL"]
SUBQUERY_URL = os.environ["SUBQUERY_URL"]

notifier = get_notifier()


def main():
    sq = AutSubquery(url=SUBQUERY_URL)
    w3 = Web3(HTTPProvider(RPC_URL))
    signer = Account.from_key(PRIVATE_KEY)
    w3.eth.default_account = signer.address
    signing_middleware = SignAndSendRawMiddlewareBuilder.build(signer)
    w3.middleware_onion.add(cast(Middleware, signing_middleware))

    service = CloseoutService(w3, sq)
    products = service.closeable_products()

    logger.info("Found %d closeable products", len(products))
    submitted_txs = []
    for product in products:
        logger.info("%s - processing closeout", product.product_id.to_0x_hex())
        product.populate()
        logger.info(
            "%s - number of accounts %d",
            product.product_id.to_0x_hex(),
            len(product.accounts),
        )
        tx_hash = product.start_closeout()
        logger.info(
            "%s - closeout tx sent: %s", product.product_id.to_0x_hex(), tx_hash.hex()
        )
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info(
            "%s - closeout tx mined in block %d",
            product.product_id.to_0x_hex(),
            receipt.blockNumber,
        )
        open_interest = service.open_interest(product.product_id)
        if open_interest > 0:
            logger.warning(
                "%s - open interest after closeout not zero!: %d",
                product.product_id,
                open_interest,
            )
        else:
            logger.info(
                "%s - open interest is zero after closeout: product closed out",
                product.product_id.to_0x_hex(),
            )
        submitted_txs.append(tx_hash)

    if len(products) > 0:
        clearing = afp.bindings.ClearingDiamond(w3)
        notify_data = [
            notifications.NotificationItem(
                title=f"Product {product.symbol}",
                values={
                    "Product ID": product.product_id.to_0x_hex(),
                    "FSP": f"{clearing.get_fsp(product.product_id)[0]}",
                    "Closeout Tx": format_link(
                        tx.to_0x_hex(), notifications.utils.LinkType.TX
                    ),
                },
            )
            for product, tx in zip(products, submitted_txs)
        ]
        notifier.notify(
            "Products Closed Out",
            f"Closeout submitted for {len(products)} products",
            notify_data,
        )
    logger.info("Closeout submitted for %d products", len(products))


if __name__ == "__main__":
    main()
