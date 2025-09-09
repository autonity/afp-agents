import logging
import time
from typing import List

import afp.bindings
from hexbytes import HexBytes
from web3 import Web3

from subquery.client import AccountInfo, AutSubquery

logger = logging.getLogger(__name__)


class ClosingProductContext:
    """
    Context manager for handling the closeout process of a single product.

    This class is responsible for:
    - Identifying all accounts with open positions in the product.
    - Validating that the total position quantity is zero before closeout.
    - Initiating the final settlement for the product.

    Attributes
    ----------
    client : AutSubquery
        Subquery client for querying account/product data.
    w3 : Web3
        Web3 instance for contract interactions.
    product_id : HexBytes
        The product identifier.
    accounts : list[AccountInfo]
        List of accounts with open positions in the product.
    """

    client: AutSubquery
    w3: Web3
    product_id: HexBytes
    accounts: list[AccountInfo]

    def __init__(
        self,
        w3: Web3,
        client: AutSubquery,
        product_id: HexBytes,
    ):
        self.w3 = w3
        self.client = client
        self.product_id = product_id

    def populate(self) -> None:
        """
        Populates the accounts that have open interest in this product.

        Queries all accounts with open interest, checks their position quantities,
        and ensures the total quantity is zero before allowing closeout.

        Raises
        ------
        RuntimeError
            If the total quantity is not zero, closeout cannot proceed.
        """
        """Populate the accounts that have open interest in this product."""
        self.accounts = self.client.accounts_in_product(self.product_id.to_0x_hex())
        total_quantity = 0
        if len(self.accounts) == 0:
            logger.warning("%s - no accounts with open interest", self.product_id.hex())
            return
        margin_account = afp.bindings.MarginAccount(self.w3, self.accounts[0].margin_account_address)

        accounts = []
        for info in self.accounts:
            balance = margin_account.position_quantity(info.account, self.product_id)
            if balance == 0:
                logger.info(
                    "%s - account %s has zero position, skipping",
                    self.product_id.hex(),
                    info.account,
                )
                continue
            logger.info(
                "%s - account %s has position %d",
                self.product_id.hex(),
                info.account,
                balance,
            )
            accounts.append(info)
            total_quantity += balance

        if total_quantity != 0:
            logger.error(
                "%s - total quantity is not zero (%d), cannot close out",
                self.product_id.hex(),
                total_quantity,
            )
            raise RuntimeError("Total quantity is not zero, cannot close out")
        else:
            logger.info("%s - total quantity is zero, ready to close out", self.product_id.hex())
            self.accounts = accounts

    def start_closeout(self) -> HexBytes:
        """
        Initiates the final settlement (closeout) for the product.

        Raises
        ------
        RuntimeError
            If there are no accounts to close out.

        Returns
        -------
        HexBytes
            The transaction hash of the closeout operation.
        """
        if len(self.accounts) == 0:
            logger.info("%s - no accounts to close out", self.product_id.hex())
            raise RuntimeError("No accounts to close out")
        clearing = afp.bindings.ClearingDiamond(self.w3)
        fn = clearing.initiate_final_settlement(
            self.product_id,
            [info.account for info in self.accounts],
        )
        return fn.transact()


class CloseoutService:
    """
    Service for identifying and processing closeable products.

    This class provides methods to:
    - Scan all products and determine which are eligible for closeout.
    - Construct ClosingProductContext objects for each closeable product.
    - Query open interest for products.

    Attributes
    ----------
    client : AutSubquery
        Subquery client for querying product/account data.
    w3 : Web3
        Web3 instance for contract interactions.
    """

    client: AutSubquery
    w3: Web3

    def __init__(self, w3: Web3, client: AutSubquery):
        self.client = client
        self.w3 = w3

    def closeable_products(self) -> List[ClosingProductContext]:
        """
        Scans all products and returns a list of closeable product contexts.

        For each product, checks if the tradeout interval has passed, open interest is positive,
        and the FSP (Final Settlement Price) has been submitted and finalized.

        Returns
        -------
        List[ClosingProductContext]
            List of contexts for each closeable product found.
        """
        now = self.w3.eth.get_block("latest")["timestamp"]
        logger.info("scanning products with Earliest FSP Submission before %d", now)
        products = self.client.products_with_fsp_passed(now)
        clearing = afp.bindings.ClearingDiamond(self.w3)

        closeable_products = []
        for product in products:
            if not product.earliest_fsp_submission_time + product.tradeout_interval < now:
                logger.info(
                    "%s - tradeout interval not passed, cannot close out",
                    product.name,
                )
                continue
            if not clearing.open_interest(HexBytes(product.id)) > 0:
                logger.info("%s - no open interest, cannot close out", product.name)
                continue
            (fsp, finalized) = clearing.get_fsp(HexBytes(product.id))
            if fsp == 0 or not finalized:
                logger.info("%s - FSP not submitted, cannot close out", product.name)
                continue
            logger.info("%s - product is closeable with fsp = %d", product.name, fsp)
            closeable_products.append(
                ClosingProductContext(self.w3, self.client, HexBytes(product.id))
            )

        return closeable_products

    def open_interest(self, product_id: HexBytes) -> int:
        """
        Returns the open interest for a given product.

        Parameters
        ----------
        product_id : HexBytes
            The product identifier.

        Returns
        -------
        int
            The open interest for the product.
        """
        clearing = afp.bindings.ClearingDiamond(self.w3)
        return clearing.open_interest(product_id)