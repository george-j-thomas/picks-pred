from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "picks-pred/0.1 (+https://github.com/george-j-thomas/picks-pred)"


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 15) -> tuple[Any, dict[str, str]]:
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp), dict(resp.headers)
