from datetime import datetime, timezone

import pytest

from picks_pred.models import Game, Team
from picks_pred.odds import american_to_implied, devig, moneyline_home_prob, spread_home_prob
from picks_pred.optimize import Weights, assign, blend, score_distribution, summarize
from picks_pred.sources import espn, manual, oddsapi

KICK = datetime(2026, 10, 4, 17, tzinfo=timezone.utc)


def game(gid, home, away, home_p=None, fpi=None, status="STATUS_SCHEDULED"):
    g = Game(gid, KICK, Team(home, f"{home} Full"), Team(away, f"{away} Full"), status)
    if home_p is not None:
        g.home_probs["book"] = home_p
        g.market_sources.add("book")
    if fpi is not None:
        g.home_probs["espn_fpi"] = fpi
    return g


def test_american_odds():
    assert american_to_implied(-150) == pytest.approx(0.6)
    assert american_to_implied("+150") == pytest.approx(0.4)
    assert american_to_implied("EVEN") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        american_to_implied(50)


def test_devig_sums_to_one():
    h, a = devig(american_to_implied(-110), american_to_implied(-110))
    assert (h, a) == pytest.approx((0.5, 0.5))
    assert moneyline_home_prob("-750", "+525") == pytest.approx(0.8465, abs=1e-3)


def test_spread_prob():
    assert spread_home_prob(0) == pytest.approx(0.5)
    assert spread_home_prob(-7) > 0.69 and spread_home_prob(7) < 0.31


def test_blend_weights_in_log_odds():
    g = game("1", "A", "B", home_p=0.6, fpi=0.8)
    final, market, model = blend(g, Weights(1, 0))
    assert (final, market, model) == pytest.approx((0.6, 0.6, 0.8))
    final, *_ = blend(g, Weights(0.5, 0.5))
    assert 0.6 < final < 0.8
    assert blend(game("2", "A", "B", fpi=0.3), Weights())[0] == pytest.approx(0.3)
    assert blend(game("3", "A", "B"), Weights())[0] is None


def test_assign_orders_by_confidence_and_picks_favorites():
    games = [game("1", "A", "B", 0.55), game("2", "C", "D", 0.2), game("3", "E", "F", 0.7)]
    picks = assign(games)
    assert [(p.team.abbr, p.points) for p in picks] == [("D", 3), ("E", 2), ("A", 1)]
    assert sorted(p.points for p in picks) == [1, 2, 3]


def test_assign_respects_locks():
    games = [game("1", "A", "B", 0.55), game("2", "C", "D", 0.2), game("3", "E", "F", 0.7)]
    picks = {p.team.abbr: p for p in assign(games, locks={"b": 3})}
    assert picks["B"].points == 3 and picks["B"].locked
    assert picks["D"].points == 2 and picks["E"].points == 1


@pytest.mark.parametrize("locks", [{"A": 4}, {"A": 1, "C": 1}, {"ZZZ": 1}])
def test_assign_rejects_bad_locks(locks):
    games = [game("1", "A", "B", 0.55), game("2", "C", "D", 0.2), game("3", "E", "F", 0.7)]
    with pytest.raises(ValueError):
        assign(games, locks=locks)


def test_assign_flags():
    g = game("1", "A", "B", 0.52, fpi=0.40)
    (pick,) = assign([g])
    assert "coin flip" in pick.flags and "FPI picks other side" in pick.flags
    (pick,) = assign([game("2", "A", "B", status="STATUS_IN_PROGRESS")])
    assert "NO DATA" in pick.flags and any("started" in f for f in pick.flags)


def test_score_distribution():
    games = [game("1", "A", "B", 0.5), game("2", "C", "D", 0.75)]
    picks = assign(games)
    dist = score_distribution(picks)
    assert sum(dist) == pytest.approx(1)
    assert dist[0] == pytest.approx(0.125) and dist[3] == pytest.approx(0.375)
    assert summarize(picks)["expected"] == pytest.approx(2 * 0.75 + 1 * 0.5)


def test_manual_overrides(tmp_path):
    csv_path = tmp_path / "o.csv"
    csv_path.write_text("team,win_prob\n# comment\nb,70%\n")
    overrides = manual.load_csv(csv_path)
    assert overrides == {"B": 0.7}
    g = game("1", "A", "B", 0.8)
    manual.apply([g], overrides)
    assert g.override_home_prob == pytest.approx(0.3)
    assert assign([g])[0].team.abbr == "B"
    with pytest.raises(ValueError):
        manual.apply([g], {"ZZZ": 0.5})


def test_oddsapi_apply_replaces_espn_lines():
    g = game("1", "A", "B", 0.9)
    events = [{
        "home_team": "A Full", "away_team": "B Full",
        "bookmakers": [
            {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                {"name": "A Full", "price": -150}, {"name": "B Full", "price": 130}]}]},
            {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                {"name": "A Full", "price": -140}, {"name": "B Full", "price": 120}]}]},
        ],
    }, {"home_team": "X", "away_team": "Y", "bookmakers": []}]
    assert oddsapi.apply([g], events) == 1
    assert g.market_sources == {"fanduel", "draftkings"}
    assert "book" not in g.home_probs
    assert 0.55 < blend(g, Weights(1, 0))[0] < 0.6


def test_espn_parse_games():
    data = {"events": [{
        "id": "401", "date": "2026-10-02T00:15Z",
        "competitions": [{
            "status": {"type": {"name": "STATUS_SCHEDULED"}},
            "competitors": [
                {"homeAway": "home", "team": {"abbreviation": "CLE", "displayName": "Cleveland Browns"}},
                {"homeAway": "away", "team": {"abbreviation": "PIT", "displayName": "Pittsburgh Steelers"}},
            ],
            "odds": [
                {"provider": {"name": "Draft Kings"},
                 "moneyline": {"home": {"close": {"odds": "+124"}}, "away": {"close": {"odds": "-148"}}}},
                {"provider": {"name": "Other"}, "pointSpread": {"home": {"close": {"line": "+3"}}}},
            ],
        }],
    }]}
    (g,) = espn.parse_games(data)
    assert g.label == "PIT @ CLE"
    assert g.market_sources == {"draftkings", "other_spread"}
    assert g.home_probs["draftkings"] == pytest.approx(0.43, abs=0.01)
    assert g.home_probs["other_spread"] < 0.5
