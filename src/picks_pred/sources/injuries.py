"""ESPN injury report (league-wide, no key), tagged with who starts per the depth charts.

Betting lines already price injuries in; this is for context in the UI.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from picks_pred.sources.http import get_json

INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
DEPTH = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/teams/{team}/depthcharts"

# Display order. IR is only shown while it's news (recently updated).
STATUSES = {"Out": 0, "Doubtful": 1, "Injured Reserve": 2, "Questionable": 3}
IR_RECENT = timedelta(days=21)
SPECIAL_TEAMS = {"pk", "p", "h", "pr", "kr", "ls"}
POSITION_WEIGHT = {"QB": 5, "WR": 3, "RB": 3, "TE": 3, "OT": 3, "DE": 3, "CB": 3, "LB": 2, "S": 2, "DT": 2, "G": 2, "C": 2}
_ATHLETE_ID = re.compile(r"(?:/id/|athletes/)(\d+)")


def _starter_ids(season: int, team_id: str) -> set[str]:
    """Athlete ids listed first at an offensive or defensive position. Players ruled out often
    drop down the chart, so a missing tag doesn't mean a player is a backup."""
    try:
        data, _ = get_json(DEPTH.format(season=season, team=team_id), timeout=10)
    except Exception:
        return set()
    starters = set()
    for formation in data.get("items", []):
        for key, pos in formation.get("positions", {}).items():
            if key in SPECIAL_TEAMS:
                continue
            for entry in pos.get("athletes", []):
                match = _ATHLETE_ID.search(entry.get("athlete", {}).get("$ref", ""))
                if match and entry.get("rank") == 1:
                    starters.add(match.group(1))
    return starters


def _athlete_id(item: dict[str, Any]) -> str | None:
    for link in item.get("athlete", {}).get("links", []):
        match = _ATHLETE_ID.search(link.get("href", ""))
        if match:
            return match.group(1)
    return None


def _date(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def parse_injuries(
    data: dict[str, Any], starters: dict[str, set[str]], now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Team abbreviation -> notable injuries, most important first."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, list[dict[str, Any]]] = {}
    for team in data.get("injuries", []):
        team_starters = starters.get(str(team.get("id")), set())
        for item in team.get("injuries", []):
            status = item.get("status")
            athlete = item.get("athlete") or {}
            abbr = (athlete.get("team") or {}).get("abbreviation")
            if status not in STATUSES or not abbr:
                continue
            when = _date(item.get("date", ""))
            if status == "Injured Reserve" and (when is None or now - when > IR_RECENT):
                continue
            details = item.get("details") or {}
            pos = (athlete.get("position") or {}).get("abbreviation", "")
            out.setdefault(abbr, []).append({
                "name": athlete.get("displayName", ""),
                "short": athlete.get("shortName", ""),
                "pos": pos,
                "status": status,
                "injury": details.get("type") if details.get("type") not in (None, "Not Specified") else "",
                "return_date": details.get("returnDate"),
                "comment": item.get("shortComment") or "",
                "date": item.get("date"),
                "starter": _athlete_id(item) in team_starters,
                "headshot": (athlete.get("headshot") or {}).get("href", ""),
            })
    for players in out.values():
        players.sort(key=lambda p: (STATUSES[p["status"]], not p["starter"], -POSITION_WEIGHT.get(p["pos"], 1), p["name"]))
    return out


def load_injuries() -> dict[str, Any]:
    data, _ = get_json(INJURIES)
    season = (data.get("season") or {}).get("year") or datetime.now(timezone.utc).year
    team_ids = [str(t.get("id")) for t in data.get("injuries", []) if t.get("id")]
    with ThreadPoolExecutor(max_workers=16) as pool:
        starters = dict(zip(team_ids, pool.map(lambda tid: _starter_ids(season, tid), team_ids)))
    return {"updated": data.get("timestamp"), "season": season, "teams": parse_injuries(data, starters)}
