import logging
from typing import List, Tuple, Optional, Dict

from eth_typing import ChecksumAddress
from gql import Client
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.aiohttp import log as requests_logger
from hexbytes import HexBytes

from .model import Account, AccountInfo, ProductInfo
from .query import (
    accounts_in_product_query,
    accounts_in_window_query,
    active_accounts_query,
    holders_of_query,
    last_trade_block_query,
    margin_accounts_query,
    products_query,
    products_with_fsp_passed_query,
    all_accounts_query,
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
        """Retrieve all AccountInfo entries for a product using cursor pagination.

        Pagination details:
        - We use GraphQL cursor pagination via the query variables `first` and `after`.
        - `first` (page_size) controls how many nodes are returned per request.
        - `after` is a Cursor value (endCursor from the previous response's pageInfo)
          and should be passed as `None` for the first page.
        - Each response includes `pageInfo` with `hasNextPage` and `endCursor`.
          We loop until `hasNextPage` is False, and collect nodes across pages.

        Parameters
        ----------
        product_id : str
            The product id to fetch holdings for.

        Returns
        -------
        list[AccountInfo]
            A combined list of AccountInfo objects for all pages.
        """
        query, parser = accounts_in_product_query(product_id)
        results: List[AccountInfo] = []
        after: Optional[str] = None
        page_size = 50

        while True:
            variables = {"productId": product_id, "first": page_size, "after": after}
            resp = self.client.execute(query, variable_values=variables)
            results.extend(parser(resp))

            page_info = resp["productHoldings"].get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        return results

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
        """Retrieve all active accounts using cursor pagination over `productHoldings`.

        Returns
        -------
        tuple[list[Account], list[HexBytes]]
            (accounts, products) aggregated across all pages.
        """
        query, parser = active_accounts_query()

        # Use sets for deduplication; Account dataclass is frozen so hashable.
        accounts_set = set()
        products_set = set()

        after: Optional[str] = None
        page_size = 50

        while True:
            variables = {"first": page_size, "after": after}
            resp = self.client.execute(query, variable_values=variables)

            accounts_page, products_page = parser(resp)

            for a in accounts_page:
                accounts_set.add(a)
            for p in products_page:
                products_set.add(p)

            page_info = resp["productHoldings"].get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        return list(accounts_set), list(products_set)

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
        """Retrieves all accounts that hold a specific product using cursor pagination.

        Parameters
        ----------
        product_id : str
            The ID of the product.

        Returns
        -------
        list[Tuple[ChecksumAddress, int]]
            A list of tuples (account address, total_quantity) holding the product,
            sorted by quantity descending.

        Notes
        -----
        - The method uses `first`/`after` cursor pagination and defaults to a
          page size of 50. Adjust `page_size` below if needed.
        - Network/GraphQL errors from `self.client.execute` will propagate.
        """
        query, parser = holders_of_query(product_id)

        # Map owner -> total quantity (sum across pages)
        totals: Dict[ChecksumAddress, int] = {}

        after: Optional[str] = None
        page_size = 50

        while True:
            variables = {"productId": product_id, "first": page_size, "after": after}
            resp = self.client.execute(query, variable_values=variables)

            page_holdings = parser(resp)
            for owner, quantity in page_holdings:
                # Sum quantities in case an owner appears multiple times across pages (shouldn't happen but
                # just in case)
                totals[owner] = totals.get(owner, 0) + int(quantity)

            page_info = resp["productHoldings"].get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        # Return list sorted by quantity descending
        sorted_holders = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        return sorted_holders

    def all_accounts(self) -> List[Account]:
        """
        Retrieve all Account objects by cursor-paginating the `marginAccountUpdates` query.

        Returns
        -------
        list[Account]
            A combined list of `Account` instances collected from all pages.

        Notes
        -----
        - Network or GraphQL errors from `self.client.execute` will propagate to the caller.
        - The parser returned by `all_accounts_query()` converts a single-page response
          into a list of `Account` objects; this method concatenates those lists.
        """
        query, parser = all_accounts_query()
        results: List[Account] = []
        after: Optional[str] = None
        page_size = 50

        while True:
            variables = {"first": page_size, "after": after}
            resp = self.client.execute(query, variable_values=variables)
            results.extend(parser(resp))

            page_info = resp["marginAccountUpdates"].get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        return results
