"""Fixed-code failures and deterministic transcript protocol primitives."""
from verification.common import Rejected, canonical, digest, fields, hex_digest, require, strict_json


def integer(value, minimum, maximum, code="invalid_integer"):
    require(type(value) is int and minimum <= value <= maximum, code)
    return value


def opaque_id(value):
    import re
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value), "invalid_identifier")
    return value


def address(value):
    import re
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", value)
            and int(value[2:], 16) != 0, "invalid_recipient")
    return value.lower()
