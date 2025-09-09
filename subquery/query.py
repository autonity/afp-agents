from typing import Callable, Dict, Any, List, Tuple

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from gql import gql
from graphql import DocumentNode

from subquery.model import AccountInfo, Account, ProductInfo


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
    query = gql(f"""
        {{
          productHoldings(filter: {{productId: {{equalTo: "{product_id}"}}, quantity: {{notEqualTo: "0"}}}}) {{
            nodes {{
              productId
              marginAccountHolding {{
                marginAccountId
                owner
              }}
              quantity
            }}
          }}
        }}
        """)

    def parser(result: Dict[str, Any]) -> List[AccountInfo]:
        accounts = []
        for holding in result["productHoldings"]["nodes"]:
            account_id = holding["marginAccountHolding"]["owner"]
            quantity = holding["quantity"]
            margin_account_address = holding["marginAccountHolding"]["marginAccountId"]
            accounts.append(
                AccountInfo(
                    account=ChecksumAddress(account_id),
                    margin_account_address=ChecksumAddress(margin_account_address),
                    quantity=int(quantity),
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


def active_accounts_query() -> (
    DocumentNode,
    Callable[[Dict[str, Any]], Tuple[List[Account], List[HexBytes]]],
):
    query = gql("""
        {
          productHoldings(filter: {quantity: {notEqualTo: "0"}}) {
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
          }
        }
        """)

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
                    name
                    state
                    earliestFSPSubmissionTime
                    tradeoutInterval
                    fsp
                }}
            }}
        }}
        """)

    def parser(result: Dict[str, Any]) -> List[ProductInfo]:
        return [
            ProductInfo(
                id=product["id"],
                name=product["name"],
                state=product["state"],
                earliest_fsp_submission_time=int(product["earliestFSPSubmissionTime"]),
                tradeout_interval=int(product["tradeoutInterval"]),
                fsp=int(product["fsp"]),
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


def holders_of_query(product_id: str) -> (DocumentNode, Callable[[Dict[str, Any]], List[Tuple[ChecksumAddress, int]]]):
    query = gql(f"""
    {{
      productHoldings(
        filter: {{
            productId: {{
                equalTo: "{product_id}"
            }},
            quantity: {{
                notEqualTo: "0"
            }}
        }}
      ){{
        nodes {{
          marginAccountHolding {{
            owner
          }}
          quantity
        }}
      }}
    }}
    """)

    def parser(result: Dict[str, Any]) -> List[Tuple[ChecksumAddress, int]]:
        return [
            (
                ChecksumAddress(account["marginAccountHolding"]["owner"]),
                int(account["quantity"])
            )
            for account in result["productHoldings"]["nodes"]
        ]
    return query, parser
