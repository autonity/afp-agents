from typing import Any, Callable, Dict, List

from eth_typing import ChecksumAddress
from gql import gql
from graphql import DocumentNode

from .model import AccountInfo, ProductInfo


def accounts_in_product_query() -> (DocumentNode, Callable[[Dict[str, Any]], List[AccountInfo]]):
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
                marginAccount {
                    contractAddress
                }
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
                        holding["marginAccountHolding"]["marginAccount"]["contractAddress"]
                    ),
                    quantity=int(holding["quantity"]),
                )
            )
        return accounts

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
