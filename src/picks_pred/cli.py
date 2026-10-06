from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

from picks_pred import report
from picks_pred.optimize import Weights, assign, summarize
from picks_pred.sources import espn, manual, oddsapi


def _kv(raw: str, cast):
    team, sep, value = raw.partition("=")
    if not sep or not team:
        raise argparse.ArgumentTypeError(f"expected TEAM=VALUE, got {raw!r}")
    return team.strip().upper(), cast(value)


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="picks-pred",
        description="Optimal NFL confidence-pool picks from sportsbook odds + ESPN FPI.",
    )
    g = p.add_argument_group("week")
    g.add_argument("--season", type=int, help="season year (default: current)")
    g.add_argument("--week", type=int, help="week number (default: current/upcoming week)")
    g.add_argument("--postseason", action="store_true", help="use postseason weeks")

    g = p.add_argument_group("data sources")
    g.add_argument("--odds-api-key", default=None,
                   help="The Odds API key for multi-book consensus (or set ODDS_API_KEY / .env)")
    g.add_argument("--books", help="comma-separated Odds API bookmaker keys, e.g. fanduel,draftkings")
    g.add_argument("--no-fpi", action="store_true", help="skip ESPN FPI")
    g.add_argument("--market-weight", type=float, default=Weights.market, help="default %(default)s")
    g.add_argument("--fpi-weight", type=float, default=Weights.model, help="default %(default)s")
    g.add_argument("--override", action="append", default=[], metavar="TEAM=PROB",
                   type=lambda s: _kv(s, manual.parse_value),
                   help="force a team's win probability, e.g. KC=0.70 (repeatable)")
    g.add_argument("--overrides-file", type=Path, help="CSV of team,win_prob overrides")

    g = p.add_argument_group("picks")
    g.add_argument("--lock", action="append", default=[], metavar="TEAM=PTS", type=lambda s: _kv(s, int),
                   help="pick already submitted, e.g. PIT=9 for a started Thursday game (repeatable)")
    g.add_argument("--max-points", type=int,
                   help="highest point value (default 16, a full week); set this if your pool uses N = number of games")

    g = p.add_argument_group("output")
    g.add_argument("--format", choices=["table", "markdown", "csv", "json"], default="table")
    g.add_argument("-o", "--out", type=Path, help="also write output to this file (markdown if --format table)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_dotenv()
    err = Console(stderr=True)

    try:
        meta, games = espn.load_week(
            season=args.season, week=args.week, season_type=3 if args.postseason else 2, fpi=not args.no_fpi
        )
    except Exception as exc:
        err.print(f"[red]failed to load ESPN schedule/odds: {exc}")
        return 1
    if not games:
        err.print("[red]no games found for that week")
        return 1

    api_key = args.odds_api_key or os.environ.get("ODDS_API_KEY")
    if api_key:
        try:
            books = [b.strip() for b in args.books.split(",")] if args.books else None
            events, remaining = oddsapi.fetch(api_key, books)
            matched = oddsapi.apply(games, events)
            if remaining is not None:
                err.print(f"note: The Odds API requests remaining this month: {remaining}", style="dim")
            err.print(f"note: The Odds API lines matched {matched}/{len(games)} games", style="dim")
        except Exception as exc:
            err.print(f"[yellow]warning: The Odds API failed ({exc}); using ESPN lines only")

    try:
        overrides = manual.load_csv(args.overrides_file) if args.overrides_file else {}
        overrides.update(dict(args.override))
        manual.apply(games, overrides)
        picks = assign(games, Weights(args.market_weight, args.fpi_weight), dict(args.lock), args.max_points)
    except (ValueError, OSError) as exc:
        err.print(f"[red]error: {exc}")
        return 2

    summary = summarize(picks)
    if args.format == "table":
        report.render_table(picks, meta, summary, Console())
        text = report.to_markdown(picks, meta, summary)
    else:
        text = {
            "markdown": lambda: report.to_markdown(picks, meta, summary),
            "csv": lambda: report.to_csv(picks),
            "json": lambda: report.to_json(picks, meta, summary),
        }[args.format]()
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        err.print(f"wrote {args.out}", style="dim")
    return 0
