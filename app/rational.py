"""Exact parsing and formatting of canonical rational numbers.

Only two spellings are accepted:

* a signed integer: ``"7"``, ``"-3"``
* a signed fraction ``p/q`` with a non-zero denominator: ``"2/3"``, ``"-4/5"``

Decimals and other approximate spellings are deliberately rejected so that no
calibration evidence can enter the service through floating point.
"""

from __future__ import annotations

import re
from fractions import Fraction

_RATIONAL_RE = re.compile(r"[+-]?\d+(?:/[+-]?\d+)?")


class RationalParseError(ValueError):
    """Raised when text is not a canonical integer or ``p/q`` fraction."""


def parse_rational(text: str) -> Fraction:
    """Parse ``text`` into an exact :class:`Fraction`.

    The denominator is normalized to be positive and the value is reduced.
    """
    if not isinstance(text, str):
        raise RationalParseError("rational value must be a string")
    candidate = text.strip()
    if not _RATIONAL_RE.fullmatch(candidate):
        raise RationalParseError(
            f"{text!r} is not an integer or a p/q fraction (decimals are not accepted)"
        )
    if "/" in candidate:
        numerator_text, denominator_text = candidate.split("/", 1)
        denominator = int(denominator_text)
        if denominator == 0:
            raise RationalParseError(f"{text!r} has a zero denominator")
        return Fraction(int(numerator_text), denominator)
    return Fraction(int(candidate), 1)


def format_rational(value: Fraction) -> str:
    """Format a reduced fraction, omitting the denominator when it is one."""
    return str(value)
