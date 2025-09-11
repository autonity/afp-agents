
from bankruptcy.service import BankruptcyService, BankruptAccountContext
from .conftest import TEST_ACCOUNTS


def test_bankrupt_accounts_empty(w3_mock, autsubquery_mock):
    autsubquery_mock.active_accounts.return_value = ([], [])

    ls = BankruptcyService(w3_mock, autsubquery_mock)
    bankrupt_accounts = ls.bankrupt_accounts()

    assert bankrupt_accounts == []
    autsubquery_mock.active_accounts.assert_called_once()


def test_liquidatable_accounts_with_data(w3_mock, autsubquery_mock, clearing_mock, margin_account_mock):
    ls = BankruptcyService(w3_mock, autsubquery_mock)
    def mae(account_id):
        index = next(
            (i for i, acc in enumerate(TEST_ACCOUNTS[0]) if acc.account_id == account_id),
            -1  # returns -1 if not found
        )
        ## half the accounts are liquidatable
        return -100 if index != -1 and index < len(TEST_ACCOUNTS[0]) // 2 else 100

    margin_account_mock.return_value.mae.side_effect = mae
    margin_account_mock.return_value.mmu.return_value = 1e18 + 1e17  # 1.1

    accounts = ls.bankrupt_accounts()
    assert len(accounts) == len(TEST_ACCOUNTS[0]) // 2  # half of the accounts are liquidatable
    for account in accounts:
        assert isinstance(account, BankruptAccountContext)
        assert account.account_id in [acc.account_id for acc in TEST_ACCOUNTS[0]]
        assert account.collateral_asset == TEST_ACCOUNTS[0][0].collateral_asset
        assert account.margin_account == TEST_ACCOUNTS[0][0].margin_account



