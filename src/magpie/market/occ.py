"""OCC option symbol parser.

Standard OCC format: AAPL260320C00275000
  - Root symbol (1-6 chars, left-aligned)
  - Expiration: YYMMDD (6 digits)
  - Option type: C (call) or P (put)
  - Strike price * 1000 (8 digits, zero-padded)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OCCComponents:
    """Parsed components of an OCC option symbol."""

    raw: str
    underlying: str
    expiry: date
    option_type: str  # "call" or "put"
    strike: float


def parse_occ(symbol: str) -> OCCComponents:
    """Parse an OCC option symbol into its components.

    Raises ValueError if the symbol cannot be parsed.
    """
    # Last 15 chars are always: YYMMDD (6) + C/P (1) + strike*1000 (8)
    if len(symbol) < 16:
        raise ValueError(f"Not a valid OCC symbol: {symbol!r}")

    strike_str = symbol[-8:]
    opt_char = symbol[-9]
    date_str = symbol[-15:-9]
    root = symbol[:-15]

    if opt_char not in ("C", "P"):
        raise ValueError(f"Invalid option type character {opt_char!r} in {symbol!r}")
    if not root:
        raise ValueError(f"Empty root symbol in {symbol!r}")

    strike = int(strike_str) / 1000.0
    option_type = "call" if opt_char == "C" else "put"
    expiry = date(2000 + int(date_str[:2]), int(date_str[2:4]), int(date_str[4:6]))

    return OCCComponents(
        raw=symbol,
        underlying=root,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
    )


def is_occ_symbol(symbol: str) -> bool:
    """Return True if symbol looks like an OCC option symbol."""
    try:
        parse_occ(symbol)
        return True
    except (ValueError, IndexError):
        return False
