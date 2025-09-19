base_url = "https://autonityscan.org"


class LinkType:
    ADDRESS = "address"
    TX = "tx"
    BLOCK = "block"


def format_link(hex_value: str, link_type=LinkType.ADDRESS) -> str:
    return f"<{base_url}/{link_type}/{hex_value}|{hex_value}>"
