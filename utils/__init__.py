from decimal import Decimal
import time
from web3 import Web3


def parse_decimal(d: Decimal | str, decimals: int) -> int:
    """Converts a Decimal or string representation of a number to an integer based on the specified decimal places.

    Parameters
    ----------
    d : decimal.Decimal | str
        The number to be converted.
    decimals : int
        The number of decimal places to consider.

    Returns
    -------
    int
        The integer representation of the number.
    """
    d = Decimal(d)
    return int(d * Decimal(10**decimals))


def format_int(i: int, decimals: int) -> Decimal:
    """Converts an integer to a Decimal based on the specified decimal places.

    Parameters
    ----------
    i : int
        The integer to be converted.
    decimals : int
        The number of decimal places to consider.

    Returns
    -------
    decimal.Decimal
        The Decimal representation of the integer.
    """
    return Decimal(i) / Decimal(10**decimals)


def wait_for_blocks(w3: Web3, num_blocks: int, poll_interval: int = 1) -> None:
    """Waits for a specified number of blocks."""
    start_block = w3.eth.get_block("latest")["number"]
    target_block = start_block + num_blocks
    while True:
        try:
            current_block = w3.eth.get_block("latest")["number"]
            if current_block >= target_block:
                break
            time.sleep(poll_interval)
        except Exception as e:
            print(f"Error while waiting for blocks: {e}")
            time.sleep(poll_interval)
