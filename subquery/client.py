import logging
from gql import Client
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.aiohttp import log as requests_logger
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from typing import List, Tuple

from subquery.model import AccountInfo, Account, ProductInfo
from subquery.query import (
    margin_accounts_query,
    accounts_in_product_query,
    products_query,
    active_accounts_query,
    products_with_fsp_passed_query,
    last_trade_block_query,
    accounts_in_window_query,
    holders_of_query,
)

requests_logger.setLevel(logging.ERROR)  # Suppress requests logging for cleaner output

class AutSubquery:
    def __init__(self, url: str):
        """Initializes the AutSubquery with a GraphQL endpoint."""
        self.transport = AIOHTTPTransport(url=url, ssl=True)
        self.client = Client(transport=self.transport, fetch_schema_from_transport=True)

    def margin_accounts(self) -> List[ChecksumAddress]:
        """Retrieves all margin account addresses in the system.

        Returns
        -------
        list[ChecksumAddress]
            A list of margin account addresses.
        """
        query, parser = margin_accounts_query()
        return parser(self.client.execute(query))

    def accounts_in_product(self, product_id: str) -> List[AccountInfo]:
        """Retrieves all accounts that have submitted orders for a specific product.

        Parameters
        ----------
        product_id : str
            The ID of the product.

        Returns
        -------
        list[AccountInfo]
        """
        query, parser = accounts_in_product_query(product_id)
        return parser(self.client.execute(query))

    def products(self) -> List[HexBytes]:
        """Retrieves all product IDs available in the system.

        Returns
        -------
        list[HexBytes]
            A list of product IDs.
        """
        query, parser = products_query()
        return parser(self.client.execute(query))

    def active_accounts(self) -> Tuple[List[Account], List[HexBytes]]:
        """Retrieves all active accounts in the system.

        Returns
        -------
        tuple[list[Account], list[HexBytes]]
            A list of active accounts with their details and a list of product IDs.
        """
        query, parser = active_accounts_query()
        return parser(self.client.execute(query))

    def products_with_fsp_passed(self, current_timestamp: int) -> List[ProductInfo]:
        """Retrieves all products whose FSP submission time has passed.

        Parameters
        ----------
        current_timestamp : int
            The current timestamp to compare against earliestFSPSubmissionTime.

        Returns
        -------
        list[ProductInfo]
            A list of products with FSP submission time passed.
        """
        query, parser = products_with_fsp_passed_query(current_timestamp)
        return parser(self.client.execute(query))

    def last_trade_block(self, product_id: str) -> int:
        """Retrieves the block number of the last trade for a specific product.

        Parameters
        ----------
        product_id : str
            The ID of the product.

        Returns
        -------
        int
            The block number of the last trade.
        """
        query, parser = last_trade_block_query(product_id)
        return parser(self.client.execute(query))

    def accounts_in_window(
        self, product_id: str, from_block: int, to_block: int
    ) -> List[ChecksumAddress]:
        """Retrieves all accounts that have submitted orders for a specific product within a block range.

        Parameters
        ----------
        product_id : str
            The ID of the product.
        from_block : int
            The starting block number (inclusive).
        to_block : int
            The ending block number (inclusive).

        Returns
        -------
        list[ChecksumAddress]
            A list of account addresses.
        """
        query, parser = accounts_in_window_query(product_id, from_block, to_block)
        return parser(self.client.execute(query))

    def holders_of(self, product_id: str) -> List[Tuple[ChecksumAddress, int]]:
        """Retrieves all accounts that hold a specific product. Sorted by quantity descending.

        Parameters
        ----------
        product_id : str
            The ID of the product.

        Returns
        -------
        list[Tuple[ChecksumAddress, int]]
            A list of tuples (account address, quantity) holding the product.
        """
        query, parser = holders_of_query(product_id)
        return parser(self.client.execute(query))
