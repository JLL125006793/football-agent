"""赔率隐含概率与去水计算。"""

from __future__ import annotations

from src.models import ODDS_KEYS, OddsSet

LABELS = {"win": "胜", "draw": "平", "loss": "负"}


def implied_probabilities(odds: OddsSet) -> dict[str, float] | None:
    """按 1/赔率 计算三项隐含概率。"""
    if not odds.is_complete():
        return None
    return {key: 1.0 / odds.get(key) for key in ODDS_KEYS if odds.get(key)}


def normalized_probabilities(odds: OddsSet) -> dict[str, float] | None:
    """去水归一化概率。"""
    implied = implied_probabilities(odds)
    if not implied:
        return None
    total = sum(implied.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in implied.items()}


def overround(odds: OddsSet) -> float | None:
    implied = implied_probabilities(odds)
    if not implied:
        return None
    return sum(implied.values()) - 1.0


def format_probability(value: float | None) -> str:
    if value is None:
        return "无法确认"
    return f"{value * 100:.1f}%"


def pick_market_probability(odds: OddsSet, selection: str) -> float | None:
    probs = normalized_probabilities(odds)
    if not probs:
        return None
    return probs.get(selection)
