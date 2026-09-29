"""ESPN public APIs: schedule, the odds ESPN displays (DraftKings), and ESPN FPI win probability."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from picks_pred.models import Game, Team
from picks_pred.odds import moneyline_home_prob, spread_home_prob
from picks_pred.sources.http import get_json

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
PREDICTOR = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
    "events/{id}/competitions/{id}/predictor"
)
FPI = "espn_fpi"


def _slug(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def fetch_scoreboard(season: int | None, week: int | None, season_type: int) -> dict[str, Any]:
    params = None
    if week is not None:
        params = {"seasontype": season_type, "week": week, "dates": season}
    data, _ = get_json(SCOREBOARD, params)
    if week is None and data.get("events") and all(
        e["competitions"][0]["status"]["type"].get("completed") for e in data["events"]
    ):
        # Current week is over; look ahead to the next one.
        nxt = data["week"]["number"] + 1
        data, _ = get_json(
            SCOREBOARD, {"seasontype": data["season"]["type"], "week": nxt, "dates": data["season"]["year"]}
        )
    return data


def _team(competitor: dict[str, Any]) -> Team:
    t = competitor["team"]
    return Team(abbr=t["abbreviation"], name=t["displayName"])


def _odds_value(node: dict[str, Any] | None, key: str) -> str | None:
    """Pull current (close) value, falling back to opening, from an ESPN odds node."""
    if not node:
        return None
    for phase in ("close", "open"):
        v = (node.get(phase) or {}).get(key)
        if v not in (None, "", "OFF"):
            return v
    return None


def parse_games(data: dict[str, Any]) -> list[Game]:
    games: list[Game] = []
    for event in data.get("events", []):
        comp = event["competitions"][0]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        game = Game(
            id=str(event["id"]),
            kickoff=datetime.fromisoformat(event["date"].replace("Z", "+00:00")),
            home=_team(home),
            away=_team(away),
            status=comp["status"]["type"]["name"],
        )
        for line in comp.get("odds") or []:
            source = _slug(line.get("provider", {}).get("name", "espn_odds"))
            ml = line.get("moneyline") or {}
            h_ml, a_ml = _odds_value(ml.get("home"), "odds"), _odds_value(ml.get("away"), "odds")
            if h_ml is None or a_ml is None:
                h_ml = (line.get("homeTeamOdds") or {}).get("moneyLine")
                a_ml = (line.get("awayTeamOdds") or {}).get("moneyLine")
            try:
                if h_ml is not None and a_ml is not None:
                    game.home_probs[source] = moneyline_home_prob(h_ml, a_ml)
                    game.market_sources.add(source)
                    continue
                spread = _odds_value((line.get("pointSpread") or {}).get("home"), "line")
                if spread is not None:
                    game.home_probs[f"{source}_spread"] = spread_home_prob(float(spread))
                    game.market_sources.add(f"{source}_spread")
            except ValueError:
                continue
        games.append(game)
    return games


def _fpi_home_prob(game_id: str) -> float | None:
    try:
        data, _ = get_json(PREDICTOR.format(id=game_id))
    except Exception:
        return None

    def gp(side: str) -> float | None:
        for stat in (data.get(side) or {}).get("statistics", []):
            if stat.get("name") == "gameProjection":
                return float(stat["value"])
        return None

    h, a = gp("homeTeam"), gp("awayTeam")
    if h is None or a is None or h + a <= 0:
        return None
    return h / (h + a)  # drop tie probability


def add_fpi(games: list[Game]) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        for game, p in zip(games, pool.map(lambda g: _fpi_home_prob(g.id), games)):
            if p is not None:
                game.home_probs[FPI] = p
    missing = [g.label for g in games if FPI not in g.home_probs and not g.started]
    if missing:
        print(f"note: ESPN FPI unavailable for {', '.join(missing)}", file=sys.stderr)


def load_week(
    season: int | None = None, week: int | None = None, season_type: int = 2, fpi: bool = True
) -> tuple[dict[str, Any], list[Game]]:
    data = fetch_scoreboard(season, week, season_type)
    games = parse_games(data)
    if fpi:
        add_fpi(games)
    meta = {
        "season": data.get("season", {}).get("year", season),
        "season_type": data.get("season", {}).get("type", season_type),
        "week": data.get("week", {}).get("number", week),
    }
    return meta, games
