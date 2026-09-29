"""JSON API for the web UI (Vercel function) plus a local dev server that also serves ``public/``.

The API returns raw per-source probabilities for a week; the browser blends and optimizes
them (public/optimize.js mirrors picks_pred.optimize) so tweaks are instant and don't cost
Odds API requests.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from picks_pred.models import Game, Team
from picks_pred.sources import espn, injuries, oddsapi

ESPN_TTL = 120
ODDS_TTL = 300
INJURY_TTL = 900
_cache: dict[Any, tuple[float, Any]] = {}

SOURCE_LABELS = {
    "espn_fpi": "ESPN FPI",
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "williamhill_us": "Caesars",
    "espnbet": "ESPN BET",
    "betrivers": "BetRivers",
    "fanatics": "Fanatics",
    "bovada": "Bovada",
    "betonlineag": "BetOnline",
    "lowvig": "LowVig",
    "mybookieag": "MyBookie",
    "ballybet": "Bally Bet",
    "hardrockbet": "Hard Rock",
}


def _cached(key: Any, ttl: float, fn: Callable[[], Any]) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


def source_label(key: str) -> str:
    base = key.removesuffix("_spread")
    label = SOURCE_LABELS.get(base, base.replace("_", " ").title())
    return f"{label} (spread)" if key.endswith("_spread") else label


def team_dict(team: Team, score: int | None) -> dict[str, Any]:
    return {
        "abbr": team.abbr,
        "name": team.name,
        "logo": team.logo,
        "color": team.color,
        "alt_color": team.alt_color,
        "score": score,
    }


def game_dict(g: Game) -> dict[str, Any]:
    winner = None
    if g.completed and g.home_score is not None and g.away_score is not None and g.home_score != g.away_score:
        winner = "home" if g.home_score > g.away_score else "away"
    return {
        "id": g.id,
        "kickoff": g.kickoff.isoformat(),
        "status": g.status,
        "status_detail": g.status_detail,
        "started": g.started,
        "completed": g.completed,
        "winner": winner,
        "line": g.line,
        "home": team_dict(g.home, g.home_score),
        "away": team_dict(g.away, g.away_score),
        "sources": [
            {"key": k, "label": source_label(k), "home_prob": p, "market": k in g.market_sources}
            for k, p in sorted(g.home_probs.items())
        ],
    }


def build_payload(
    season: int | None,
    week: int | None,
    season_type: int,
    api_key: str | None = None,
    key_source: str | None = None,
    books: list[str] | None = None,
) -> dict[str, Any]:
    meta, games = _cached(("espn", season, week, season_type), ESPN_TTL,
                          lambda: espn.load_week(season, week, season_type))
    # load_week mutates nothing afterwards, but oddsapi.apply does: work on fresh copies.
    meta, games = json.loads(json.dumps(meta)), [_copy_game(g) for g in games]

    odds: dict[str, Any] = {"enabled": bool(api_key), "key_source": key_source, "matched": 0,
                            "remaining": None, "error": None, "skipped": False}
    if api_key and all(g.started for g in games):
        odds["skipped"] = True  # the feed only has upcoming games; don't spend a request
    elif api_key:
        digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        try:
            events, remaining = _cached(("odds", digest, tuple(books or ())), ODDS_TTL,
                                        lambda: oddsapi.fetch(api_key, books))
            odds["matched"] = oddsapi.apply(games, events)
            odds["remaining"] = remaining
        except Exception as exc:  # surfaced to the UI, ESPN data still returned
            odds["error"] = _describe(exc)
    return {**meta, "odds_api": odds, "generated_at": time.time(), "games": [game_dict(g) for g in games]}


def _copy_game(g: Game) -> Game:
    from dataclasses import replace

    return replace(g, home_probs=dict(g.home_probs), market_sources=set(g.market_sources))


def _describe(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code == 401:
        return "The Odds API rejected the key (401)"
    if code == 429:
        return "The Odds API quota exhausted (429)"
    return f"The Odds API request failed: {exc}"


def _int(qs: dict[str, list[str]], name: str) -> int | None:
    raw = (qs.get(name) or [""])[0]
    return int(raw) if raw.strip().isdigit() else None


def _json(start_response, status: str, body: Any, cache: str = "no-store") -> list[bytes]:
    data = json.dumps(body).encode()
    start_response(status, [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(data))),
        ("Cache-Control", cache),
    ])
    return [data]


def app(environ: dict[str, Any], start_response) -> list[bytes]:
    """WSGI app for ``GET /api/games?season=&week=&type=&books=`` (header ``X-Odds-Api-Key``)."""
    if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
        return _json(start_response, "405 Method Not Allowed", {"error": "GET only"})
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    user_key = (environ.get("HTTP_X_ODDS_API_KEY") or "").strip() or None
    server_key = os.environ.get("ODDS_API_KEY") or None
    api_key = user_key or server_key
    books = [b.strip() for b in (qs.get("books") or [""])[0].split(",") if b.strip()] or None
    season_type = _int(qs, "type") or 2
    try:
        payload = build_payload(
            _int(qs, "season"), _int(qs, "week"), season_type, api_key,
            "browser" if user_key else ("server" if server_key else None), books,
        )
    except Exception as exc:
        return _json(start_response, "502 Bad Gateway", {"error": f"failed to load ESPN data: {exc}"})
    if not payload["games"]:
        return _json(start_response, "404 Not Found", {"error": "no games found for that week", **payload})
    cache = "private, no-store" if user_key else "public, s-maxage=120, stale-while-revalidate=600"
    return _json(start_response, "200 OK", payload, cache)


def injuries_app(environ: dict[str, Any], start_response) -> list[bytes]:
    """WSGI app for ``GET /api/injuries``: current ESPN injury report by team abbreviation."""
    if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
        return _json(start_response, "405 Method Not Allowed", {"error": "GET only"})
    try:
        payload = _cached(("injuries",), INJURY_TTL, injuries.load_injuries)
    except Exception as exc:
        return _json(start_response, "502 Bad Gateway", {"error": f"failed to load injuries: {exc}"})
    return _json(start_response, "200 OK", payload, "public, s-maxage=900, stale-while-revalidate=3600")


PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"


def dev_app(environ: dict[str, Any], start_response) -> list[bytes]:
    """Local stand-in for Vercel: ``/api/*`` goes to :func:`app`, everything else is static."""
    path = environ.get("PATH_INFO", "/")
    if path.rstrip("/") == "/api/injuries":
        return injuries_app(environ, start_response)
    if path.startswith("/api/"):
        return app(environ, start_response)
    target = (PUBLIC_DIR / path.lstrip("/")).resolve()
    if target.is_dir():
        target = target / "index.html"
    if not target.is_relative_to(PUBLIC_DIR) or not target.is_file():
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    start_response("200 OK", [("Content-Type", ctype), ("Cache-Control", "no-cache")])
    return [target.read_bytes()]


def serve() -> None:
    import argparse
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    parser = argparse.ArgumentParser(prog="picks-pred-web", description="Run the web UI locally.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    class Server(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    class QuietHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            if str(code) != "200":
                super().log_request(code, size)

    if not PUBLIC_DIR.is_dir():
        raise SystemExit(f"static files not found at {PUBLIC_DIR}; run from a source checkout")
    httpd = make_server(args.host, args.port, dev_app, server_class=Server, handler_class=QuietHandler)
    print(f"picks-pred web UI on http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
