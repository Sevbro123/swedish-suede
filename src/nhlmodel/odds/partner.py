"""Current moneylines from the NHL's betting partner (``/v1/partner-game/{country}/now``).

The endpoint has current prices only, no history (docs/phase0_data_discovery.md §3a), so paper trading
records them going forward: every live run, and every minute the watcher polls games about to start,
appends the prices to the odds log. Rows carry the NHL game id, so no team-name matching is needed.

Odds log (data/processed/odds_log.csv), one row per (game, price change):

    game_id           int     NHL game id
    observed_at       str     UTC ISO time we read the price (the live run's ``now``)
    home_ml, away_ml  int     2-way moneyline (overtime and shootout included), American odds
    book              str     the partner book named in the response
    odds_updated_utc  str     the response's lastUpdatedUTC (may be empty)
    source            str     "nhl_partner_game"
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ..ingest.http import CachedClient
from ..ingest.nhl import WEB, _key
from .vig import overround

ODDS_COLS = ["game_id", "observed_at", "home_ml", "away_ml", "book", "odds_updated_utc", "source"]
SOURCE = "nhl_partner_game"
MAX_OVERROUND = 0.15   # anything wider is not a normal pregame 2-way price


def to_american(v: Any) -> float | None:
    """A price as the endpoint writes it (American, or decimal outside the US) -> American odds."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if abs(x) >= 100:
        return x
    if 1 < x < 100:   # decimal
        return round((x - 1) * 100) if x >= 2 else round(-100 / (x - 1))
    return None


def _moneyline(team: dict[str, Any]) -> float | None:
    for o in team.get("odds") or []:
        if o.get("description") == "MONEY_LINE_2_WAY":
            return to_american(o.get("value"))
    return None


def parse(data: dict[str, Any]) -> pd.DataFrame:
    """One row per game with a usable 2-way moneyline on both sides (``observed_at`` not set)."""
    book = (data.get("bettingPartner") or {}).get("name") or ""
    rows = []
    for g in data.get("games") or []:
        h, a = _moneyline(g.get("homeTeam") or {}), _moneyline(g.get("awayTeam") or {})
        if h is None or a is None or not g.get("gameId"):
            continue
        if not 0 <= float(overround(h, a)) <= MAX_OVERROUND:
            continue
        rows.append({"game_id": int(g["gameId"]), "home_ml": int(h), "away_ml": int(a), "book": book,
                     "odds_updated_utc": data.get("lastUpdatedUTC") or "", "source": SOURCE})
    return pd.DataFrame(rows, columns=[c for c in ODDS_COLS if c != "observed_at"])


def fetch(client: CachedClient, now: pd.Timestamp, country: str = "US") -> pd.DataFrame:
    """Read the partner's current moneylines, stamped ``observed_at=now``. Kept as a dated raw snapshot."""
    snap = now.strftime("%Y%m%dT%H%M%SZ")
    data = client.get_json(f"{WEB}/partner-game/{country}/now", _key(f"nhl_web/partner_game/{country}", snap))
    return parse(data).assign(observed_at=now.isoformat())[ODDS_COLS]


def append_log(log: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Add ``new`` prices, skipping any game whose price hasn't changed since its last logged row."""
    if new.empty:
        return log
    if len(log):
        last = log.sort_values("observed_at").groupby("game_id").tail(1).set_index("game_id")
        prev = new["game_id"].map(last["home_ml"]), new["game_id"].map(last["away_ml"])
        new = new[~((prev[0] == new["home_ml"]) & (prev[1] == new["away_ml"]))]
    return pd.concat([log, new], ignore_index=True)[ODDS_COLS]
