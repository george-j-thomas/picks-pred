"""Vercel function: GET /api/games. See picks_pred.web.app."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from picks_pred.web import app  # noqa: E402

__all__ = ["app"]
