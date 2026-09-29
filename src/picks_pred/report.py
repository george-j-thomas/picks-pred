from __future__ import annotations

import csv
import io
import json
from typing import Any

from rich.console import Console
from rich.table import Table

from picks_pred.models import Pick


def _pct(p: float | None) -> str:
    return "-" if p is None else f"{p * 100:.1f}%"


def _kick(pick: Pick) -> str:
    return pick.game.kickoff.astimezone().strftime("%a %m/%d %I:%M%p").replace(" 0", " ")


def _rows(picks: list[Pick]) -> list[dict[str, Any]]:
    return [
        {
            "points": p.points,
            "pick": p.team.abbr,
            "opponent": p.opponent.abbr,
            "home": p.team is p.game.home,
            "game": p.game.label,
            "win_prob": round(p.win_prob, 4),
            "market_prob": None if p.market_prob is None else round(p.market_prob, 4),
            "fpi_prob": None if p.model_prob is None else round(p.model_prob, 4),
            "kickoff": p.game.kickoff.isoformat(),
            "locked": p.locked,
            "sources": sorted(p.game.home_probs),
            "flags": p.flags,
        }
        for p in picks
    ]


def _title(meta: dict[str, Any]) -> str:
    kind = "Postseason " if meta.get("season_type") == 3 else ""
    return f"{meta.get('season')} NFL {kind}Week {meta.get('week')} - confidence picks"


def _summary_lines(summary: dict[str, float]) -> list[str]:
    return [
        f"Expected score: {summary['expected']:.1f} / {summary['max']} "
        f"(sd {summary['sd']:.1f}, 80% range {summary['p10']}-{summary['p90']})",
        f"Expected correct picks: {summary['expected_wins']:.1f}",
    ]


def render_table(picks: list[Pick], meta: dict[str, Any], summary: dict[str, float], console: Console) -> None:
    table = Table(title=_title(meta), title_style="bold")
    for col, kw in [
        ("Pts", {"justify": "right", "style": "bold"}),
        ("Pick", {"style": "green"}),
        ("vs", {}),
        ("Win %", {"justify": "right", "style": "bold"}),
        ("Market", {"justify": "right"}),
        ("FPI", {"justify": "right"}),
        ("Kickoff", {}),
        ("Notes", {"style": "yellow"}),
    ]:
        table.add_column(col, **kw)
    for p in picks:
        pick = f"{p.team.abbr}{'' if p.team is p.game.home else ' (away)'}"
        pts = f"{p.points}🔒" if p.locked else str(p.points)
        table.add_row(
            pts, pick, p.opponent.abbr, _pct(p.win_prob), _pct(p.market_prob), _pct(p.model_prob),
            _kick(p), ", ".join(p.flags),
        )
    console.print(table)
    books = sorted({s for p in picks for s in p.game.market_sources})
    console.print(f"Market sources: {', '.join(books) or 'none'}", style="dim")
    for line in _summary_lines(summary):
        console.print(line)


def to_markdown(picks: list[Pick], meta: dict[str, Any], summary: dict[str, float]) -> str:
    out = [f"# {_title(meta)}", "", "| Pts | Pick | vs | Win % | Market | FPI | Kickoff | Notes |",
           "|---:|---|---|---:|---:|---:|---|---|"]
    for p in picks:
        out.append(
            f"| {p.points}{' (locked)' if p.locked else ''} | {p.team.abbr} | {p.opponent.abbr} | "
            f"{_pct(p.win_prob)} | {_pct(p.market_prob)} | {_pct(p.model_prob)} | {_kick(p)} | "
            f"{', '.join(p.flags)} |"
        )
    out += [""] + [f"- {line}" for line in _summary_lines(summary)] + [""]
    return "\n".join(out)


def to_csv(picks: list[Pick]) -> str:
    buf = io.StringIO()
    rows = _rows(picks)
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    for r in rows:
        writer.writerow({**r, "sources": ";".join(r["sources"]), "flags": ";".join(r["flags"])})
    return buf.getvalue()


def to_json(picks: list[Pick], meta: dict[str, Any], summary: dict[str, float]) -> str:
    return json.dumps({**meta, "summary": summary, "picks": _rows(picks)}, indent=2)
