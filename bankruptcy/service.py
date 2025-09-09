import logging
from typing import List

import afp.bindings
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import Web3

from subquery.client import AutSubquery

logger = logging.getLogger(__name__)


class BankruptAccountContext:
    """
    Context manager for handling a single bankrupt account during the bankruptcy process.

    This class encapsulates all logic required to:
    - Load and manage positions for a bankrupt account.
    - Identify Loss Absorbing Accounts (LAAs) for each position.
    - Initiate loss mutualization on-chain.
    - Query and aggregate position quantities for accounts.

    Attributes
    ----------
    client : AutSubquery
        Subquery client for querying blockchain/account data.
    w3 : Web3
        Web3 instance for contract interactions.
    account_id : ChecksumAddress
        The address of the bankrupt account.
    collateral_asset : ChecksumAddress
        The collateral asset associated with the account.
    margin_account : ChecksumAddress
        The margin account contract address.
    positions : list[afp.bindings.PositionData]
        List of positions held by the account.
    """

    client: AutSubquery
    w3: Web3

    account_id: ChecksumAddress
    collateral_asset: ChecksumAddress
    margin_account: ChecksumAddress
    positions: list[afp.bindings.PositionData]

    def __init__(
        self,
        w3: Web3,
        client: AutSubquery,
        account_id: ChecksumAddress,
        collateral_asset: ChecksumAddress,
        margin_account: ChecksumAddress,
    ):
        self.w3 = w3
        self.client = client
        self.account_id = account_id
        self.collateral_asset = collateral_asset
        self.margin_account = margin_account
        self.positions = []

    def populate(self) -> None:
        """
        Loads all positions for the current account from the margin account contract.

        This method fetches the list of position identifiers for the account and retrieves detailed position data
        for each, storing them in `self.positions`.

        Raises
        ------
        Exception
            If unable to fetch positions or position data.
        """
        margin_account = afp.bindings.MarginAccount(self.w3, self.margin_account)
        positions = margin_account.positions(self.account_id)
        self.positions = [
            margin_account.position_data(self.account_id, position)
            for position in positions
        ]

    def start_loss_mutualization(self) -> HexBytes:
        """
        Initiates the loss mutualization process for the current bankrupt account.

        Requires that `populate()` has been called to load positions.

        This method calls the clearing contract to distribute losses across Loss Absorbing Accounts (LAAs)
        for each position held by the bankrupt account, executing the mutualization transaction on-chain.

        Returns
        -------
        HexBytes
            The transaction hash of the mutualization operation.
        """
        clearing = afp.bindings.ClearingDiamond(self.w3)
        product_ids = [pos.position_id for pos in self.positions]
        laas = self.get_laas()
        fn = clearing.mutualize_losses(
            self.account_id, self.collateral_asset, product_ids, laas
        )
        return fn.transact()

    def get_laas(self) -> List[List[ChecksumAddress]]:
        """
        Retrieves the Loss Absorbing Accounts (LAAs) for each position in the current account context.

        For each position:
        - Fetches all accounts that have traded within the mark price window of 30 seconds.
        - If these accounts do not provide sufficient quantity to offset the bankrupt account's position,
          fills the list with additional accounts holding the highest available quantities.

        Returns
        -------
        List[List[ChecksumAddress]]
            A list of lists, where each inner list contains the ChecksumAddresses
            of accounts that can absorb losses for a given position in self.positions.

        Raises
        ------
        Exception
            If no positions are found or `populate()` has not been called.
        """
        if len(self.positions) == 0:
            raise Exception("No positions found, or populate() not called")
        laas = []
        for position in self.positions:
            last_trade_block = self.client.last_trade_block(
                position.position_id.to_0x_hex()
            )
            accounts = self.client.accounts_in_window(
                position.position_id.to_0x_hex(),
                last_trade_block - 30,
                last_trade_block,
            )
            accounts = self.fill_laas_for(
                position.position_id,
                -position.quantity,
                accounts,
            )
            laas.append(accounts)
        return laas

    def fill_laas_for(
        self, product_id: HexBytes, needed_quantity: int, laas: List[ChecksumAddress]
    ) -> List[ChecksumAddress]:
        """
        Ensures the Loss Absorbing Accounts (LAAs) list has sufficient quantity to offset a bankrupt position.

        Checks whether the provided LAAs (accounts from the 30s trading window) have enough quantity in the required direction.
        If not, adds accounts from all holders, starting with those holding the largest quantity in the correct direction,
        until the total quantity is sufficient.

        Parameters
        ----------
        product_id : HexBytes
            The product identifier for the position.
        needed_quantity : int
            The quantity required to offset the bankrupt account's position.
        laas : List[ChecksumAddress]
            Initial list of LAAs from the recent trading window.

        Returns
        -------
        List[ChecksumAddress]
            The completed list of LAAs with sufficient quantity to absorb the loss.
        """
        contained_quantity = sum(
            [
                quantity
                for quantity in self.quantities(laas, product_id)
                if quantity * needed_quantity > 0
            ]
        )
        if abs(contained_quantity) >= abs(needed_quantity):
            return laas
        ## should be sorted by quantity descending
        holders = self.client.holders_of(product_id.to_0x_hex())
        if needed_quantity < 0:
            ## we want to use the highest negative holders first
            holders = holders[::-1]
        k = 0
        while abs(contained_quantity) < abs(needed_quantity) and k < len(holders):
            (account, balance) = holders[k]
            ## skip if already in laas or if balance is in the wrong direction
            if account in laas or balance * needed_quantity < 0:
                k += 1
                continue
            laas.append(account)
            contained_quantity += balance
            k += 1
        return laas

    def quantities(
        self, accounts: List[ChecksumAddress], product_id: HexBytes
    ) -> List[int]:
        """
        Retrieves the position quantities for a list of accounts for a specific product.

        Parameters
        ----------
        accounts : List[ChecksumAddress]
            The accounts to query for position quantities.
        product_id : HexBytes
            The product identifier to query.

        Returns
        -------
        List[int]
            A list of position quantities for each account.
        """
        margin_account = afp.bindings.MarginAccount(self.w3, self.margin_account)
        return [
            margin_account.position_quantity(account, product_id)
            for account in accounts
        ]


class BankruptcyService:
    """
    Service for identifying and processing bankrupt accounts.

    This class provides methods to:
    - Scan all active accounts and determine which are bankrupt.
    - Construct BankruptAccountContext objects for each bankrupt account.
    - Facilitate the workflow for mutualizing losses and handling bankruptcy events.

    Attributes
    ----------
    client : AutSubquery
        Subquery client for querying blockchain/account data.
    w3 : Web3
        Web3 instance for contract interactions.
    """

    client: AutSubquery
    w3: Web3

    def __init__(self, w3: Web3, client: AutSubquery):
        self.client = client
        self.w3 = w3

    def bankrupt_accounts(self) -> list[BankruptAccountContext]:
        """
        Scans all active accounts and returns a list of bankrupt account contexts.

        For each active account, checks if the account's MAE (Margin Account Equity) is negative and MMU (Maintenance
         Margin Used) is non-zero. If so, constructs a BankruptAccountContext for further processing.

        Returns
        -------
        list[BankruptAccountContext]
            List of contexts for each bankrupt account found.
        """
        accounts, _ = self.client.active_accounts()
        logger.info("Found %d active accounts", len(accounts))
        bankrupt_accounts = []
        for acct in accounts:
            logger.info("Checking account %s", acct.account_id)
            margin_account_contract = afp.bindings.MarginAccount(
                self.w3, acct.margin_account
            )
            mae = margin_account_contract.mae(acct.account_id)
            if not (mae < 0):
                logger.info("Account %s is not bankrupt", acct.account_id)
                continue
            logger.info("Found bankrupt account %s", acct.account_id)
            mmu = margin_account_contract.mmu(acct.account_id)
            if mmu == 0:
                logger.info(
                    "Account %s has zero MMU, nothing we can do, skipping",
                    acct.account_id,
                )
                continue
            logger.info(
                "Account (%s)\n\tMAE: %s\n\tMMU %s",
                acct.account_id,
                f"{mae}",
                f"{mmu}",
            )

            bankrupt_accounts.append(
                BankruptAccountContext(
                    self.w3,
                    self.client,
                    acct.account_id,
                    acct.collateral_asset,
                    acct.margin_account,
                )
            )

        return bankrupt_accounts
