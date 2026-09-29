"""Conversions between betting odds and win probabilities."""

from __future__ import annotations

import math
from statistics import NormalDist

# Standard deviation of NFL final margin vs. closing spread (historical ~13-14 points).
NFL_MARGIN_SD = 13.45


def american_to_implied(odds: float | str) -> float:
    """Implied probability (including vig) of American odds like -150 or '+130'."""
    o = float(str(odds).replace("EVEN", "100").strip())
    if o == 0 or -100 < o < 100:
        raise ValueError(f"invalid American odds: {odds!r}")
    return -o / (-o + 100) if o < 0 else 100 / (o + 100)


def devig(a_implied: float, b_implied: float) -> tuple[float, float]:
    """Remove the bookmaker margin by normalizing a two-way market to sum to 1."""
    total = a_implied + b_implied
    return a_implied / total, b_implied / total


def moneyline_home_prob(home_odds: float | str, away_odds: float | str) -> float:
    home, _ = devig(american_to_implied(home_odds), american_to_implied(away_odds))
    return home


def spread_home_prob(home_spread: float) -> float:
    """Home win probability from a point spread (negative = home favored)."""
    return NormalDist().cdf(-home_spread / NFL_MARGIN_SD)


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def inv_logit(x: float) -> float:
    return 1 / (1 + math.exp(-x))
