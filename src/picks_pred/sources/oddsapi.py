"""The Odds API (https://the-odds-api.com): moneylines from many US books (FanDuel, DraftKings, ...).

Requires a free API key. Each run costs 1 request per region/market (we use 1).
"""

from __future__ import annotations

from typing import Any

from picks_pred.models import Game
from picks_pred.odds import moneyline_home_prob
from picks_pred.sources.http import get_json

URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


def fetch(api_key: str, bookmakers: list[str] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Return (events, requests remaining this month)."""
    params: dict[str, Any] = {"apiKey": api_key, "markets": "h2h", "oddsFormat": "american"}
    if bookmakers:
        params["bookmakers"] = ",".join(bookmakers)
    else:
        params["regions"] = "us"
    data, headers = get_json(URL, params)
    return data, {k.lower(): v for k, v in headers.items()}.get("x-requests-remaining")


def apply(games: list[Game], events: list[dict[str, Any]]) -> int:
    """Attach each bookmaker's de-vigged home win probability to matching games.

    Replaces ESPN-sourced market lines for matched games so each book is counted once.
    Returns the number of games matched.
    """
    by_teams = {(g.home.name, g.away.name): g for g in games}
    matched = 0
    for ev in events:
        game = by_teams.get((ev.get("home_team"), ev.get("away_team")))
        if game is None:
            continue
        probs: dict[str, float] = {}
        for book in ev.get("bookmakers", []):
            market = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
            if not market:
                continue
            prices = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            if game.home.name in prices and game.away.name in prices:
                try:
                    probs[book["key"]] = moneyline_home_prob(prices[game.home.name], prices[game.away.name])
                except ValueError:
                    continue
        if not probs:
            continue
        for src in list(game.market_sources):
            game.home_probs.pop(src, None)
        game.market_sources = set(probs)
        game.home_probs.update(probs)
        matched += 1
    return matched
