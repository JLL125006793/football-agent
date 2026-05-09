"""进球期望与泊松比分模型。"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial

from src.models import Match
from src.odds import normalized_probabilities


@dataclass(frozen=True)
class GoalModel:
    home_expected: float | None
    away_expected: float | None
    note: str
    home_win: float | None
    draw: float | None
    away_win: float | None
    handicap_win: float | None
    handicap_draw: float | None
    handicap_loss: float | None
    most_likely_score: str
    most_likely_score_probability: float | None
    low_score_cluster: float | None
    mid_score_cluster: float | None
    high_score_cluster: float | None


def estimate_expected_goals(match: Match) -> tuple[float | None, float | None, str]:
    """优先用真实 xG/xGA；缺少时用近10场进失球做保守估算。"""
    has_xg = all(value is not None for value in (match.home_xg, match.away_xg, match.home_xga, match.away_xga))
    if has_xg:
        home_expected = (match.home_xg + match.away_xga) / 2
        away_expected = (match.away_xg + match.home_xga) / 2
        return _clamp_goal(home_expected), _clamp_goal(away_expected), "使用录入的xG/xGA数据"

    has_recent = all(
        value is not None
        for value in (
            match.recent_home_goals_for,
            match.recent_home_goals_against,
            match.recent_away_goals_for,
            match.recent_away_goals_against,
        )
    )
    if has_recent:
        home_expected = (match.recent_home_goals_for + match.recent_away_goals_against) / 2
        away_expected = (match.recent_away_goals_for + match.recent_home_goals_against) / 2
        return (
            _clamp_goal(home_expected),
            _clamp_goal(away_expected),
            "xG/xGA为公开数据不足下的模型估算",
        )

    probs = normalized_probabilities(match.spf_odds)
    if probs:
        home_prob = probs.get("win", 0.33)
        away_prob = probs.get("loss", 0.33)
        goal_diff = (home_prob - away_prob) * 1.5
        base_total = 2.45
        home_expected = (base_total + goal_diff) / 2 + 0.12
        away_expected = (base_total - goal_diff) / 2 - 0.12
        return (
            _clamp_goal(home_expected),
            _clamp_goal(away_expected),
            "xG/xGA为公开数据不足下的模型估算，仅作辅助判断；模型置信度低",
        )

    return None, None, "无法确认：缺少xG/xGA、近10场进失球与完整赔率数据"


def build_goal_model(match: Match, max_goals: int = 8) -> GoalModel:
    home_expected, away_expected, note = estimate_expected_goals(match)
    if home_expected is None or away_expected is None:
        return GoalModel(None, None, note, None, None, None, None, None, None, "无法确认", None, None, None, None)

    matrix: dict[tuple[int, int], float] = {}
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            matrix[(home_goals, away_goals)] = _poisson(home_goals, home_expected) * _poisson(away_goals, away_expected)

    home_win = sum(prob for (h, a), prob in matrix.items() if h > a)
    draw = sum(prob for (h, a), prob in matrix.items() if h == a)
    away_win = sum(prob for (h, a), prob in matrix.items() if h < a)

    handicap = match.handicap or 0
    handicap_win = sum(prob for (h, a), prob in matrix.items() if h + handicap > a)
    handicap_draw = sum(prob for (h, a), prob in matrix.items() if h + handicap == a)
    handicap_loss = sum(prob for (h, a), prob in matrix.items() if h + handicap < a)

    score, score_probability = max(matrix.items(), key=lambda item: item[1])
    low = sum(prob for (h, a), prob in matrix.items() if h + a <= 2)
    mid = sum(prob for (h, a), prob in matrix.items() if 3 <= h + a <= 4)
    high = sum(prob for (h, a), prob in matrix.items() if h + a >= 5)

    return GoalModel(
        home_expected=home_expected,
        away_expected=away_expected,
        note=note,
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        handicap_win=handicap_win,
        handicap_draw=handicap_draw,
        handicap_loss=handicap_loss,
        most_likely_score=f"{score[0]}-{score[1]}",
        most_likely_score_probability=score_probability,
        low_score_cluster=low,
        mid_score_cluster=mid,
        high_score_cluster=high,
    )


def probability_interval(value: float | None, spread: float = 0.03) -> str:
    if value is None:
        return "无法确认"
    low = max(0.0, value - spread)
    high = min(1.0, value + spread)
    return f"{low * 100:.1f}%–{high * 100:.1f}%"


def _poisson(goals: int, expected: float) -> float:
    return exp(-expected) * expected**goals / factorial(goals)


def _clamp_goal(value: float) -> float:
    return round(min(max(value, 0.2), 4.5), 2)
