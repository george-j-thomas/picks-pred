import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from picks_pred import web
from picks_pred.models import Game, Team
from picks_pred.optimize import Weights, assign

ROOT = Path(__file__).resolve().parents[1]
KICK = datetime(2026, 10, 4, 17, tzinfo=timezone.utc)


def make_games(started=False):
    spec = [
        ("1", "BAL", "TEN", 0.85, 0.84), ("2", "CLE", "PIT", 0.43, 0.45), ("3", "CIN", "JAX", 0.57, 0.45),
        ("4", "NYG", "ARI", 0.49, 0.46), ("5", "SF", "DEN", 0.58, 0.77), ("6", "LV", "KC", 0.34, None),
        ("7", "HOU", "DAL", None, 0.46),
    ]
    games = []
    for gid, h, a, mkt, fpi in spec:
        g = Game(gid, KICK, Team(h, f"{h} Full", color="112233"), Team(a, f"{a} Full"),
                 "STATUS_FINAL" if started else "STATUS_SCHEDULED", completed=started)
        if mkt is not None:
            g.home_probs["draftkings"] = mkt
            g.market_sources.add("draftkings")
        if fpi is not None:
            g.home_probs["espn_fpi"] = fpi
        games.append(g)
    return games


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("weights", [Weights(), Weights(1, 0), Weights(0.3, 0.7)])
def test_js_optimizer_matches_python(weights, tmp_path):
    games = make_games()
    locks = {"PIT": 7}
    py = [(p.team.abbr, p.points, round(p.win_prob, 9)) for p in assign(games, weights, locks)]

    payload = {
        "games": [web.game_dict(g) for g in games],
        "weights": {"market": weights.market, "model": weights.model},
        "locks": {"2": {"team": "PIT", "points": 7}},
    }
    module = tmp_path / "optimize.mjs"  # .mjs so any Node version loads it as ESM
    module.write_text((ROOT / "public" / "optimize.js").read_text())
    script = f"""
      import {{ assign }} from {json.dumps(module.as_uri())};
      let raw = ""; for await (const c of process.stdin) raw += c;
      const d = JSON.parse(raw);
      const {{ picks, errors }} = assign(d.games, {{ weights: d.weights, locks: d.locks }});
      console.log(JSON.stringify({{ errors, picks: picks.map(p => [p.team.abbr, p.points, +p.winProb.toFixed(9)]) }}));
    """
    out = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(payload),
                         capture_output=True, text=True, check=True)
    js = json.loads(out.stdout)
    assert js["errors"] == []
    assert [tuple(x) for x in js["picks"]] == py


def call(environ):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(web.app({"REQUEST_METHOD": "GET", **environ}, start_response))
    return captured["status"], captured["headers"], json.loads(body)


@pytest.fixture
def fake_espn(monkeypatch):
    web._cache.clear()
    calls = {"odds": 0, "started": False}

    def load_week(season, week, season_type):
        meta = {"season": 2026, "season_type": season_type, "week": week or 4, "calendar": []}
        return meta, make_games(started=calls["started"])

    def fetch(api_key, books):
        calls["odds"] += 1
        calls["key"] = api_key
        return [{"home_team": "BAL Full", "away_team": "TEN Full", "bookmakers": [
            {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                {"name": "BAL Full", "price": -500}, {"name": "TEN Full", "price": 400}]}]}]}], "321"

    monkeypatch.setattr(web.espn, "load_week", load_week)
    monkeypatch.setattr(web.oddsapi, "fetch", fetch)
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    return calls


def test_api_without_key(fake_espn):
    status, headers, body = call({"QUERY_STRING": "week=5&type=2"})
    assert status.startswith("200")
    assert body["week"] == 5 and len(body["games"]) == 7
    assert body["odds_api"]["enabled"] is False and fake_espn["odds"] == 0
    assert "s-maxage" in headers["Cache-Control"]
    g = body["games"][0]
    assert g["home"]["abbr"] == "BAL" and g["home"]["color"] == "112233"
    assert {s["label"] for s in g["sources"]} == {"DraftKings", "ESPN FPI"}


def test_api_with_browser_key(fake_espn):
    status, headers, body = call({"QUERY_STRING": "", "HTTP_X_ODDS_API_KEY": "abc"})
    assert status.startswith("200")
    assert fake_espn["key"] == "abc"
    assert body["odds_api"] == {"enabled": True, "key_source": "browser", "matched": 1, "remaining": "321",
                                "error": None, "skipped": False}
    bal = body["games"][0]
    assert [s["key"] for s in bal["sources"] if s["market"]] == ["fanduel"]
    assert headers["Cache-Control"] == "private, no-store"
    # cached ESPN data must not be polluted by the Odds API merge
    _, _, again = call({"QUERY_STRING": ""})
    assert [s["key"] for s in again["games"][0]["sources"] if s["market"]] == ["draftkings"]


def test_api_server_key_and_skip_past_weeks(fake_espn, monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "server")
    fake_espn["started"] = True
    _, _, body = call({"QUERY_STRING": "week=3"})
    assert body["odds_api"]["key_source"] == "server"
    assert body["odds_api"]["skipped"] is True and fake_espn["odds"] == 0


def test_dev_app_serves_static_and_blocks_traversal():
    def run(path):
        captured = {}
        body = b"".join(web.dev_app({"PATH_INFO": path}, lambda s, h: captured.update(status=s)))
        return captured["status"], body

    status, body = run("/")
    assert status.startswith("200") and b"<title>" in body
    assert run("/../pyproject.toml")[0].startswith("404")
