from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Team:
    abbr: str
    name: str  # full display name, e.g. "Pittsburgh Steelers"


@dataclass
class Game:
    id: str
    kickoff: datetime
    home: Team
    away: Team
    status: str = "STATUS_SCHEDULED"
    # Home-team win probabilities keyed by source name (e.g. "draftkings", "fpi").
    home_probs: dict[str, float] = field(default_factory=dict)
    # Source name -> is it a betting market (vs. a model like FPI).
    market_sources: set[str] = field(default_factory=set)
    override_home_prob: float | None = None

    @property
    def started(self) -> bool:
        return self.status not in ("STATUS_SCHEDULED", "STATUS_POSTPONED")

    @property
    def label(self) -> str:
        return f"{self.away.abbr} @ {self.home.abbr}"

    def team(self, abbr: str) -> Team | None:
        abbr = abbr.upper()
        for t in (self.home, self.away):
            if t.abbr == abbr:
                return t
        return None


@dataclass
class Pick:
    game: Game
    team: Team
    opponent: Team
    win_prob: float
    points: int
    locked: bool = False
    market_prob: float | None = None
    model_prob: float | None = None
    flags: list[str] = field(default_factory=list)
