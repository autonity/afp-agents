from decimal import Decimal
from unittest.mock import MagicMock

from liquidation.service import LiquidatingAccountContext, LiquidationService
from subquery.client import AutSubquery
from tests.conftest import TEST_ACCOUNTS


def test_auction_config_cache(clearing_mock, autsubquery_mock, w3_mock):
    ls = LiquidationService(w3_mock, autsubquery_mock)
    duration, buffer = ls.auction_config()
    assert duration == 100
    assert buffer == Decimal(10)/Decimal(1e4)

    ## call again to ensure caching works
    _, _ = ls.auction_config()
    clearing_mock.return_value.auction_config.assert_called_once()

def test_liquidatable_accounts_empty():
    w3_mock = MagicMock()
    aut_subquery_mock = MagicMock(spec=AutSubquery)
    aut_subquery_mock.active_accounts.return_value = ([], [])

    ls = LiquidationService(w3_mock, aut_subquery_mock)
    liquidatable_accounts = ls.liquidatable_accounts()

    assert liquidatable_accounts == []
    aut_subquery_mock.active_accounts.assert_called_once()


def test_liquidatable_accounts_with_data(w3_mock, autsubquery_mock, clearing_mock, margin_account_mock):
    ls = LiquidationService(w3_mock, autsubquery_mock)
    def is_liquidatable(account_id, collateral_asset):
        index = next(
            (i for i, acc in enumerate(TEST_ACCOUNTS[0]) if acc.account_id == account_id),
            -1  # returns -1 if not found
        )
        ## half the accounts are liquidatable
        return index != -1 and index < len(TEST_ACCOUNTS[0]) // 2
    clearing_mock.return_value.is_liquidatable.side_effect = is_liquidatable

    margin_account_mock.return_value.mae.return_value = 1e18  # 1
    margin_account_mock.return_value.mmu.return_value = 1e18 + 1e17  # 1.1

    accounts = ls.liquidatable_accounts()
    assert len(accounts) == len(TEST_ACCOUNTS[0]) // 2  # half of the accounts are liquidatable
    for account in accounts:
        assert isinstance(account, LiquidatingAccountContext)
        assert account.account_id in [acc.account_id for acc in TEST_ACCOUNTS[0]]
        assert account.collateral_asset == TEST_ACCOUNTS[0][0].collateral_asset
        assert account.margin_account == TEST_ACCOUNTS[0][0].margin_account



