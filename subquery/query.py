from typing import Any, Callable, Dict, List, Tuple

from eth_typing import ChecksumAddress
from gql import gql
from graphql import DocumentNode
from hexbytes import HexBytes

from .model import Account, AccountInfo, ProductInfo


def margin_accounts_query() -> (
    DocumentNode,
    Callable[[Dict[str, Any]], List[ChecksumAddress]],
):
    query = gql("""
        {
          marginAccounts {
            nodes {
              id
            }
          }
        }
        """)

    def parser(result):
        return [
            ChecksumAddress(account["id"])
            for account in result["marginAccounts"]["nodes"]
        ]

    return query, parser


def accounts_in_product_query(
    product_id: str,
) -> (DocumentNode, Callable[[Dict[str, Any]], List[AccountInfo]]):
    query = gql(
        """
        query($productId: String!, $first: Int!, $after: Cursor) {
          productHoldings(
            filter: {productId: {equalTo: $productId}, quantity: {notEqualTo: "0"}}
            first: $first
            after: $after
          ) {
            nodes {
              productId
              marginAccountHolding {
                marginAccountId
                owner
              }
              quantity
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
    )

    def parser(result: Dict[str, Any]) -> List[AccountInfo]:
        accounts: List[AccountInfo] = []
        for holding in result["productHoldings"]["nodes"]:
            accounts.append(
                AccountInfo(
                    account=ChecksumAddress(holding["marginAccountHolding"]["owner"]),
                    margin_account_address=ChecksumAddress(
                        holding["marginAccountHolding"]["marginAccountId"]
                    ),
                    quantity=int(holding["quantity"]),
                )
            )
        return accounts

    return query, parser


def products_query() -> (DocumentNode, Callable[[Dict[str, Any]], List[HexBytes]]):
    query = gql("""
        {
          products {
            nodes {
              id
            }
          }
        }
        """)

    def parser(result: Dict[str, Any]) -> List[HexBytes]:
        return [HexBytes(product["id"]) for product in result["products"]["nodes"]]

    return query, parser


def all_accounts_query() -> (DocumentNode, Callable[[Dict[str, Any]], List[Account]]):
    query = gql(
        """
        query($first: Int!, $after: Cursor) {
          marginAccountUpdates(
            filter: {updateType: {equalTo: DEPOSIT}}
            distinct: [OWNER]
            first: $first
            after: $after
          ) {
            nodes {
                owner
                marginAccount {
                    collateralAsset
                    id
                }
             }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
    )

    def parser(result: Dict[str, Any]) -> List[Account]:
        accounts: List[Account] = []
        for account in result["marginAccountUpdates"]["nodes"]:
            accounts.append(
                Account(
                    account_id=ChecksumAddress(account["owner"]),
                    margin_account=ChecksumAddress(account["marginAccount"]["id"]),
                    collateral_asset=ChecksumAddress(
                        account["marginAccount"]["collateralAsset"]
                    ),
                )
            )
        return accounts

    return query, parser


def active_accounts_query() -> (
    DocumentNode,
    Callable[[Dict[str, Any]], Tuple[List[Account], List[HexBytes]]],
):
    # Cursor-paginated query: callers should provide `$first` (page size) and
    # `$after` (Cursor) and iterate using `pageInfo.hasNextPage` / `pageInfo.endCursor`.
    query = gql(
        """
        query($first: Int!, $after: Cursor) {
          productHoldings(filter: {quantity: {notEqualTo: "0"}}, first: $first, after: $after) {
            nodes {
              product {
                id
              }
              marginAccountHolding {
                owner
                marginAccount {
                    id
                    collateralAsset
                }
              }
              quantity
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
    )

    def parser(result: Dict[str, Any]) -> (List[Account], List[HexBytes]):
        accounts = set()
        products = set()
        for account in result["productHoldings"]["nodes"]:
            product_id = HexBytes(account["product"]["id"])
            products.add(product_id)
            accounts.add(
                Account(
                    account_id=ChecksumAddress(
                        account["marginAccountHolding"]["owner"]
                    ),
                    margin_account=ChecksumAddress(
                        account["marginAccountHolding"]["marginAccount"]["id"]
                    ),
                    collateral_asset=ChecksumAddress(
                        account["marginAccountHolding"]["marginAccount"][
                            "collateralAsset"
                        ]
                    ),
                )
            )
        return list(accounts), list(products)

    return query, parser


def products_with_fsp_passed_query(
    current_timestamp: int,
) -> (DocumentNode, Callable[[Dict[str, any]], List[ProductInfo]]):
    query = gql(f"""
        {{
            products(filter: {{
                earliestFSPSubmissionTime: {{lessThan: "{current_timestamp}"}}
            }}) {{
                nodes {{
                    id
                    symbol
                    state
                    earliestFSPSubmissionTime
                    tradeoutInterval
                    fsp {{
                        fsp
                        blockNumber
                    }}
                }}
            }}
        }}
        """)

    def parser(result: Dict[str, Any]) -> List[ProductInfo]:
        return [
            ProductInfo(
                id=product["id"],
                name=product["symbol"],
                state=product["state"],
                earliest_fsp_submission_time=int(product["earliestFSPSubmissionTime"]),
                tradeout_interval=int(product["tradeoutInterval"]),
                fsp=int(product["fsp"]["fsp"] if product["fsp"] else 0),
            )
            for product in result["products"]["nodes"]
        ]

    return query, parser


def last_trade_block_query(
    product_id: str,
) -> (DocumentNode, Callable[[Dict[str, Any]], int]):
    query = gql(f"""
    {{
      trades(
        filter: {{
            product: {{
                id: {{
                    equalTo: "{product_id}"
                }}
            }}
        }}
        orderBy: BLOCK_NUMBER_DESC
        first: 1
    ){{
        nodes {{
          blockNumber
        }}
      }}
    }}
    """)

    def parser(result: Dict[str, Any]) -> int:
        if len(result["trades"]["nodes"]) == 0:
            return 0
        return int(result["trades"]["nodes"][0]["blockNumber"])

    return query, parser


def accounts_in_window_query(
    product_id: str, from_block: int, to_block: int
) -> (DocumentNode, Callable[[Dict[str, Any]], List[ChecksumAddress]]):
    query = gql(f"""
    {{
      trades(
        filter: {{
            product: {{
                id: {{
                    equalTo: "{product_id}"
                }}
            }},
            blockNumber: {{
                greaterThanOrEqualTo: "{from_block}",
                lessThanOrEqualTo: "{to_block}"
            }}
        }}
        orderBy: BLOCK_NUMBER_DESC
      ){{
        nodes {{
            accounts {{
                nodes {{
                    marginAccountId
                }}
            }}
        }}
      }}
    }}
    """)

    def parser(result: Dict[str, Any]) -> List[ChecksumAddress]:
        accounts = set()
        for trade in result["trades"]["nodes"]:
            for account in trade["accounts"]["nodes"]:
                accounts.add(ChecksumAddress(account["marginAccountId"]))
        return list(accounts)

    return query, parser


def holders_of_query(
    product_id: str,
) -> (DocumentNode, Callable[[Dict[str, Any]], List[Tuple[ChecksumAddress, int]]]):
    # Cursor-paginated query: uses $productId, $first and $after (Cursor).
    # The caller should loop pages using pageInfo.hasNextPage / pageInfo.endCursor.
    query = gql(
        """
        query($productId: String!, $first: Int!, $after: Cursor) {
          productHoldings(
            filter: {
              productId: { equalTo: $productId },
              quantity: { notEqualTo: "0" }
            }
            first: $first
            after: $after
          ) {
            nodes {
              marginAccountHolding {
                owner
              }
              quantity
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
    )

    def parser(result: Dict[str, Any]) -> List[Tuple[ChecksumAddress, int]]:
        return [
            (
                ChecksumAddress(account["marginAccountHolding"]["owner"]),
                int(account["quantity"]),
            )
            for account in result["productHoldings"]["nodes"]
        ]

    return query, parser
