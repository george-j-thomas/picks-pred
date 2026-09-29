import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from picks_pred import web
from picks_pred.sources import injuries

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

POOL_SCRIPT = r"""
import assert from "node:assert/strict";
import { optimizeForPool } from "./pool.js";
import { assign } from "./optimize.js";

// 12 games, max-points plan: pick the favorite, rank by confidence.
const probs = [0.86, 0.8, 0.76, 0.71, 0.68, 0.64, 0.61, 0.58, 0.55, 0.53, 0.52, 0.34];
const order = probs.map((p, i) => [Math.max(p, 1 - p), i]).sort((a, b) => a[0] - b[0]);
const points = Array(probs.length);
order.forEach(([, i], rank) => (points[i] = rank + 1));
const games = probs.map((p, i) => ({
  id: String(i), q: p, m: p, home: p >= 0.5, points: points[i],
  fixedSide: i === 0, fixedPoints: i === 0,
}));

const run = (entries) => optimizeForPool({ games, entries, seed: 7, optSims: 1500, evalSims: 3000 });
const a = run(40), b = run(40);
assert.deepEqual(a, b, "deterministic for a seed");
assert.ok(a.pWin >= a.pWinBase, "never worse than max-points on the eval sims");
assert.equal(a.changed, a.pWin > a.pWinBase);
assert.deepEqual(a.plan.map((p) => p.points).sort((x, y) => x - y), points.slice().sort((x, y) => x - y));
assert.equal(a.plan[0].home, true, "locked side kept");
assert.equal(a.plan[0].points, points[0], "locked points kept");
assert.ok(a.winningScore > 0 && a.winningScore <= 78);

// A big pool should push at least one underdog pick.
const big = run(150);
assert.ok(big.changed && big.plan.some((p, i) => p.home !== games[i].home), "contrarian in big pool");

// assign() applies a plan without locking it, and flags underdogs.
const espnGames = probs.slice(0, 3).map((p, i) => ({
  id: String(i), completed: false,
  home: { abbr: "H" + i }, away: { abbr: "A" + i },
  sources: [{ key: "draftkings", home_prob: p, market: true }],
}));
const { picks, errors } = assign(espnGames, {
  plan: { 0: { team: "A0", points: 3 }, 1: { team: "H1", points: 1 }, 2: { team: "H2", points: 2 } },
});
assert.deepEqual(errors, []);
const got = picks.map((p) => [p.team.abbr, p.points]).sort();
assert.deepEqual(got, [["A0", 3], ["H1", 1], ["H2", 2]]);
const a0 = picks.find((p) => p.team.abbr === "A0");
assert.ok(a0.flags.includes("contrarian") && !a0.locked);
console.log("ok");
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_pool_search(tmp_path):
    (tmp_path / "package.json").write_text('{"type": "module"}')
    for name in ("pool.js", "optimize.js"):
        shutil.copy(ROOT / "public" / name, tmp_path / name)
    (tmp_path / "t.js").write_text(POOL_SCRIPT)
    out = subprocess.run(["node", "t.js"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def item(name, status, pid, pos="WR", abbr="PIT", date="2026-09-30T12:00Z", injury="Knee"):
    return {
        "status": status, "date": date, "shortComment": f"{name} note",
        "details": {"type": injury, "returnDate": "2026-10-05"},
        "athlete": {
            "displayName": name, "shortName": name[:5], "position": {"abbreviation": pos},
            "team": {"abbreviation": abbr}, "links": [{"href": f"https://espn.com/nfl/player/_/id/{pid}/x"}],
        },
    }


def test_parse_injuries_filters_tags_and_sorts():
    data = {"injuries": [{"id": "23", "injuries": [
        item("Q Backup", "Questionable", 1),
        item("Q Starter QB", "Questionable", 2, pos="QB"),
        item("Old IR", "Injured Reserve", 3, date="2026-08-01T00:00Z"),
        item("New IR", "Injured Reserve", 4),
        item("Out Guy", "Out", 5, injury="Not Specified"),
        item("Active", "Active", 6),
        item("Day", "Day-To-Day", 7),
    ]}]}
    out = injuries.parse_injuries(data, {"23": {"2", "5"}}, now=NOW)
    players = out["PIT"]
    assert [p["name"] for p in players] == ["Out Guy", "New IR", "Q Starter QB", "Q Backup"]
    assert [p["starter"] for p in players] == [True, False, True, False]
    assert players[0]["injury"] == "" and players[1]["injury"] == "Knee"
    assert players[1]["return_date"] == "2026-10-05"


def test_injuries_endpoint(monkeypatch):
    web._cache.clear()
    calls = []

    def fake():
        calls.append(1)
        return {"updated": "now", "season": 2026, "teams": {"PIT": []}}

    monkeypatch.setattr(injuries, "load_injuries", fake)
    for path in ("/api/injuries", "/api/injuries/"):
        captured = {}
        body = b"".join(web.dev_app({"PATH_INFO": path, "REQUEST_METHOD": "GET"},
                                    lambda s, h: captured.update(status=s, headers=dict(h))))
        assert captured["status"].startswith("200")
        assert json.loads(body)["teams"] == {"PIT": []}
        assert "s-maxage" in captured["headers"]["Cache-Control"]
    assert len(calls) == 1  # cached

    web._cache.clear()
    monkeypatch.setattr(injuries, "load_injuries", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    captured = {}
    body = b"".join(web.injuries_app({"REQUEST_METHOD": "GET"}, lambda s, h: captured.update(status=s)))
    assert captured["status"].startswith("502") and "down" in json.loads(body)["error"]
