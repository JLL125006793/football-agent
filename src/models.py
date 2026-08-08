"""数据模型与输入校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_FIELDS = [
    "match_id",
    "start_time",
    "league",
    "home_team",
    "away_team",
    "spf_odds",
    "handicap",
    "rqspf_odds",
    "data_source",
    "official_data_confirmed",
    "odds_complete",
    "fetch_status",
    "injury_note",
    "lineup_note",
    "motivation_note",
    "weather_note",
]

ODDS_KEYS = ("win", "draw", "loss")
UNKNOWN = "无法确认"


@dataclass(frozen=True)
class OddsSet:
    """胜/平/负三项赔率。"""

    win: float | None
    draw: float | None
    loss: float | None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "OddsSet":
        if not isinstance(value, dict):
            return cls(None, None, None)
        return cls(
            _to_float(value.get("win")),
            _to_float(value.get("draw")),
            _to_float(value.get("loss")),
        )

    def is_complete(self) -> bool:
        return all(getattr(self, key) is not None and getattr(self, key) > 1 for key in ODDS_KEYS)

    def get(self, key: str) -> float | None:
        return getattr(self, key)

    def display(self) -> str:
        if not self.is_complete():
            return UNKNOWN
        return f"{self.win:.2f}/{self.draw:.2f}/{self.loss:.2f}"


@dataclass(frozen=True)
class Match:
    """单场比赛输入数据。"""

    match_id: str
    start_time: str
    league: str
    home_team: str
    away_team: str
    spf_odds: OddsSet
    handicap: int | float | None
    rqspf_odds: OddsSet
    recent_home_goals_for: float | None
    recent_home_goals_against: float | None
    recent_away_goals_for: float | None
    recent_away_goals_against: float | None
    home_xg: float | None
    away_xg: float | None
    home_xga: float | None
    away_xga: float | None
    injury_note: str
    motivation_note: str
    lineup_note: str
    weather_note: str
    lineup_confirmed: bool
    official_data_confirmed: bool
    odds_complete: bool
    odds_movement_note: str
    odds_conflict_note: str
    data_source: str
    fetch_status: str
    missing_fields: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Match":
        explicit_missing = tuple(str(field) for field in raw.get("missing_fields", []) if field)
        missing = tuple(field for field in REQUIRED_FIELDS if field not in raw)
        spf_odds = OddsSet.from_dict(raw.get("spf_odds"))
        rqspf_odds = OddsSet.from_dict(raw.get("rqspf_odds"))
        handicap = _to_float(raw.get("handicap"))
        odds_complete = bool(raw.get("odds_complete", False)) and spf_odds.is_complete() and rqspf_odds.is_complete() and handicap is not None
        computed_missing = _computed_missing(raw, spf_odds, rqspf_odds, handicap)
        return cls(
            match_id=str(raw.get("match_id", UNKNOWN)),
            start_time=str(raw.get("start_time", UNKNOWN)),
            league=str(raw.get("league", UNKNOWN)),
            home_team=str(raw.get("home_team", UNKNOWN)),
            away_team=str(raw.get("away_team", UNKNOWN)),
            spf_odds=spf_odds,
            handicap=handicap,
            rqspf_odds=rqspf_odds,
            recent_home_goals_for=_to_float(raw.get("recent_home_goals_for")),
            recent_home_goals_against=_to_float(raw.get("recent_home_goals_against")),
            recent_away_goals_for=_to_float(raw.get("recent_away_goals_for")),
            recent_away_goals_against=_to_float(raw.get("recent_away_goals_against")),
            home_xg=_to_float(raw.get("home_xg")),
            away_xg=_to_float(raw.get("away_xg")),
            home_xga=_to_float(raw.get("home_xga")),
            away_xga=_to_float(raw.get("away_xga")),
            injury_note=_clean_note(raw.get("injury_note")) or UNKNOWN,
            motivation_note=_clean_note(raw.get("motivation_note")) or UNKNOWN,
            lineup_note=_clean_note(raw.get("lineup_note")) or ("已确认" if raw.get("lineup_confirmed") else UNKNOWN),
            weather_note=_clean_note(raw.get("weather_note")) or UNKNOWN,
            lineup_confirmed=bool(raw.get("lineup_confirmed", False)),
            official_data_confirmed=bool(raw.get("official_data_confirmed", False)),
            odds_complete=odds_complete,
            odds_movement_note=_clean_note(raw.get("odds_movement_note")) or UNKNOWN,
            odds_conflict_note=_clean_note(raw.get("odds_conflict_note")) or "无",
            data_source=_clean_note(raw.get("data_source")) or "手动录入",
            fetch_status=_clean_note(raw.get("fetch_status")) or UNKNOWN,
            missing_fields=tuple(sorted(set(missing + explicit_missing + computed_missing))),
        )

    @property
    def matchup(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    def has_complete_odds(self) -> bool:
        return self.odds_complete and self.spf_odds.is_complete() and self.rqspf_odds.is_complete() and self.handicap is not None

    def has_enough_goal_data(self) -> bool:
        has_recent = all(
            value is not None
            for value in (
                self.recent_home_goals_for,
                self.recent_home_goals_against,
                self.recent_away_goals_for,
                self.recent_away_goals_against,
            )
        )
        has_xg = all(value is not None for value in (self.home_xg, self.away_xg, self.home_xga, self.away_xga))
        return has_recent or has_xg

    def has_fetch_failure(self) -> bool:
        return self.fetch_status not in ("成功", "手动录入")

    def has_odds_conflict(self) -> bool:
        return self.odds_conflict_note not in ("", "无", UNKNOWN)

    def is_data_complete_for_selection(self) -> bool:
        return (
            not self.missing_fields
            and self.has_complete_odds()
            and not self.has_fetch_failure()
            and not self.has_odds_conflict()
        )


def _computed_missing(raw: dict[str, Any], spf_odds: OddsSet, rqspf_odds: OddsSet, handicap: float | None) -> tuple[str, ...]:
    missing: list[str] = []
    for field in ("match_id", "start_time", "league", "home_team", "away_team"):
        if raw.get(field) in (None, "", UNKNOWN):
            missing.append(field)
    if not spf_odds.is_complete():
        missing.append("spf_odds")
    if handicap is None:
        missing.append("handicap")
    if not rqspf_odds.is_complete():
        missing.append("rqspf_odds")
    return tuple(missing)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def _clean_note(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
