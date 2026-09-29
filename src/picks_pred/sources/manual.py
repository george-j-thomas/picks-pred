"""Manual win-probability overrides, e.g. for late injury news or a line from another site.

CSV columns: ``team,win_prob`` with win_prob as 0.72, 72 or 72%. An optional ``team,win_prob``
header row and lines starting with '#' are ignored. An override replaces the blended estimate.
"""

from __future__ import annotations

import csv
from pathlib import Path

from picks_pred.models import Game


def parse_value(raw: str) -> float:
    v = float(raw.strip().rstrip("%"))
    if v > 1:
        v /= 100
    if not 0 <= v <= 1:
        raise ValueError(f"win probability out of range: {raw!r}")
    return v


def load_csv(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(newline="") as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].lstrip().startswith("#")]
    for row in rows:
        if row[0].strip().lower() == "team":
            continue
        out[row[0].strip().upper()] = parse_value(row[1])
    return out


def apply(games: list[Game], overrides: dict[str, float]) -> None:
    remaining = dict(overrides)
    for game in games:
        for abbr, prob in overrides.items():
            if game.home.abbr == abbr:
                game.override_home_prob = prob
            elif game.away.abbr == abbr:
                game.override_home_prob = 1 - prob
            else:
                continue
            remaining.pop(abbr, None)
    if remaining:
        raise ValueError(f"override team(s) not playing this week: {', '.join(sorted(remaining))}")
