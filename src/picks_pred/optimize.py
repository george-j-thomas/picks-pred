"""Blend probabilities and assign confidence points.

Expected score is sum(points_i * p_i). By the rearrangement inequality it is maximized
by picking the more likely winner of every game and giving the largest remaining point
values to the highest win probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass

from picks_pred.models import Game, Pick
from picks_pred.odds import inv_logit, logit

COIN_FLIP = 0.55
DISAGREE_GAP = 0.10


@dataclass
class Weights:
    market: float = 0.8
    model: float = 0.2


def blend(game: Game, weights: Weights) -> tuple[float | None, float | None, float | None]:
    """Return (final_home_prob, market_home_prob, model_home_prob) for a game.

    Market sources are averaged together, model sources are averaged together, and the
    two groups are combined with a weighted average in log-odds space.
    """
    markets = [p for s, p in game.home_probs.items() if s in game.market_sources]
    models = [p for s, p in game.home_probs.items() if s not in game.market_sources]
    market = inv_logit(sum(map(logit, markets)) / len(markets)) if markets else None
    model = inv_logit(sum(map(logit, models)) / len(models)) if models else None

    if game.override_home_prob is not None:
        return game.override_home_prob, market, model

    parts = [(market, weights.market), (model, weights.model)]
    parts = [(p, w) for p, w in parts if p is not None and w > 0]
    if not parts:
        return None, market, model
    total_w = sum(w for _, w in parts)
    final = inv_logit(sum(logit(p) * w for p, w in parts) / total_w)
    return final, market, model


def assign(
    games: list[Game],
    weights: Weights | None = None,
    locks: dict[str, int] | None = None,
    max_points: int | None = None,
) -> list[Pick]:
    """Pick a winner and a unique confidence value for every game.

    ``locks`` maps a team abbreviation to points already submitted (e.g. a Thursday game);
    those picks are kept and the remaining point values are optimized over the other games.
    """
    weights = weights or Weights()
    locks = {k.upper(): v for k, v in (locks or {}).items()}
    n = max_points or len(games)
    available = set(range(1, n + 1))

    picks: list[Pick] = []
    open_picks: list[Pick] = []
    locked_abbrs: set[str] = set()

    for game in games:
        home_p, market, model = blend(game, weights)
        flags: list[str] = []
        if home_p is None:
            home_p = 0.5
            flags.append("NO DATA")

        lock_team = next((game.team(a) for a in locks if game.team(a)), None)
        if lock_team is not None:
            team = lock_team
        else:
            team = game.home if home_p >= 0.5 else game.away
        is_home = team is game.home
        opp = game.away if is_home else game.home

        def side(p: float | None) -> float | None:
            return None if p is None else (p if is_home else 1 - p)

        win_p = side(home_p)
        pick = Pick(game, team, opp, win_p, 0, market_prob=side(market), model_prob=side(model), flags=flags)

        if max(win_p, 1 - win_p) < COIN_FLIP:
            flags.append("coin flip")
        if market is not None and model is not None:
            if (market - 0.5) * (model - 0.5) < 0:
                flags.append("FPI picks other side")
            elif abs(market - model) >= DISAGREE_GAP:
                flags.append("FPI disagrees")
        if game.override_home_prob is not None:
            flags.append("override")

        if lock_team is not None:
            pts = locks[team.abbr]
            if pts not in available:
                raise ValueError(f"locked points {pts} for {team.abbr} is invalid or used twice (1..{n})")
            available.discard(pts)
            locked_abbrs.add(team.abbr)
            pick.points, pick.locked = pts, True
        else:
            if game.started:
                flags.append("already started - use --lock")
            open_picks.append(pick)
        picks.append(pick)

    unknown = set(locks) - locked_abbrs
    if unknown:
        raise ValueError(f"--lock team(s) not playing this week: {', '.join(sorted(unknown))}")
    if len(available) < len(open_picks):
        raise ValueError(f"not enough point values: {len(open_picks)} games but only {sorted(available)} left")

    points = sorted(available, reverse=True)[: len(open_picks)]
    for pick, pts in zip(sorted(open_picks, key=lambda p: p.win_prob, reverse=True), points):
        pick.points = pts

    return sorted(picks, key=lambda p: p.points, reverse=True)


def score_distribution(picks: list[Pick]) -> list[float]:
    """Exact probability of each total score (index = points), assuming independent games."""
    dist = [1.0]
    for pick in picks:
        new = [0.0] * (len(dist) + pick.points)
        for score, prob in enumerate(dist):
            if prob:
                new[score + pick.points] += prob * pick.win_prob
                new[score] += prob * (1 - pick.win_prob)
        dist = new
    return dist


def summarize(picks: list[Pick]) -> dict[str, float]:
    dist = score_distribution(picks)
    mean = sum(s * p for s, p in enumerate(dist))
    var = sum((s - mean) ** 2 * p for s, p in enumerate(dist))

    def pct(q: float) -> int:
        acc = 0.0
        for s, p in enumerate(dist):
            acc += p
            if acc >= q:
                return s
        return len(dist) - 1

    return {
        "max": sum(p.points for p in picks),
        "expected": mean,
        "sd": var**0.5,
        "p10": pct(0.10),
        "p50": pct(0.50),
        "p90": pct(0.90),
        "expected_wins": sum(p.win_prob for p in picks),
    }
