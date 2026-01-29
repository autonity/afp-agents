import logging
from typing import List, Optional

from gql import Client
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.aiohttp import log as requests_logger

from .model import AccountInfo, ProductInfo
from .query import (
    accounts_in_product_query,
    products_with_fsp_passed_query,
)

requests_logger.setLevel(logging.ERROR)  # Suppress requests logging for cleaner output


class AutSubquery:
    def __init__(self, url: str):
        """Initializes the AutSubquery with a GraphQL endpoint."""
        self.transport = AIOHTTPTransport(url=url, ssl=True)
        self.client = Client(transport=self.transport, fetch_schema_from_transport=True)

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
        query, parser = accounts_in_product_query()
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
