"""单场风险评分与分类。"""

from __future__ import annotations

from dataclasses import dataclass

from src.models import Match, UNKNOWN
from src.odds import normalized_probabilities
from src.poisson import GoalModel


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    category: str
    reason: str
    risks: list[str]
    component_scores: dict[str, int]


def assess_match(match: Match, goal_model: GoalModel) -> RiskAssessment:
    risks: list[str] = []

    clarity = 20
    if not match.official_data_confirmed:
        clarity -= 15
        risks.append("官方数据无法确认")
    if match.missing_fields:
        clarity -= min(10, len(match.missing_fields) * 3)
        risks.append(f"缺失字段：{','.join(match.missing_fields)}")
    if match.has_fetch_failure():
        clarity = 0
        risks.append(f"页面抓取失败：{match.fetch_status}")
    clarity = max(0, clarity)

    motivation = 15
    if match.motivation_note == UNKNOWN:
        motivation -= 8
        risks.append("战意无法确认")
    elif any(word in match.motivation_note for word in ("不明", "存疑")):
        motivation -= 10
        risks.append(f"战意风险：{match.motivation_note}")
    motivation = max(0, motivation)

    lineup = 15
    if not match.lineup_confirmed or match.lineup_note == UNKNOWN:
        lineup -= 7
        risks.append("阵容无法确认")
    if match.injury_note == UNKNOWN:
        lineup -= 5
        risks.append("伤停无法确认")
    elif any(word in match.injury_note for word in ("缺阵", "伤", "轮换", "停赛")):
        lineup -= 8
        risks.append(f"伤停/轮换风险：{match.injury_note}")
    lineup = max(0, lineup)

    odds_support = 0
    if not match.has_complete_odds():
        risks.append("赔率不完整或让球数据缺失")
    else:
        odds_support = 18
        if normalized_probabilities(match.spf_odds) and normalized_probabilities(match.rqspf_odds):
            odds_support += 4
        if match.odds_movement_note != UNKNOWN and not any(word in match.odds_movement_note for word in ("异常", "跳", "造热")):
            odds_support += 3
        elif match.odds_movement_note != UNKNOWN:
            odds_support -= 6
            risks.append(f"赔率变化风险：{match.odds_movement_note}")
    if match.has_odds_conflict():
        odds_support = max(0, odds_support - 15)
        risks.append(match.odds_conflict_note)
    odds_support = max(0, min(25, odds_support))

    value = 0
    if goal_model.home_win is not None and match.has_complete_odds():
        value = 10
        if _model_and_odds_not_conflicting(match, goal_model):
            value += 5
        else:
            value -= 4
            risks.append("盘口方向与进球模型存在分歧")
    else:
        risks.append("赔率性价比无法确认")
    value = max(0, min(15, value))

    parlay_fit = 0
    if match.has_complete_odds() and not match.has_fetch_failure() and not match.has_odds_conflict():
        parlay_fit = 7
        if match.official_data_confirmed and match.lineup_confirmed and match.injury_note != UNKNOWN:
            parlay_fit = 10
    else:
        risks.append("二串一适配度不足")

    components = {
        "基本面清晰度": clarity,
        "战意明确度": motivation,
        "阵容稳定性": lineup,
        "盘口赔率支持度": odds_support,
        "赔率性价比": value,
        "二串一适配度": parlay_fit,
    }
    score = sum(components.values())
    category = _category(score, match)
    reason = _reason(category, risks, match)
    return RiskAssessment(score=score, category=category, reason=reason, risks=risks or ["暂无明显风险，但仍需临场复核"], component_scores=components)


def _category(score: int, match: Match) -> str:
    if match.has_fetch_failure() or match.has_odds_conflict() or not match.has_complete_odds():
        return "D"
    if score >= 88:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    return "D"


def _reason(category: str, risks: list[str], match: Match) -> str:
    if category == "A":
        return "方向较清晰、赔率和模型较一致，可作为核心胆或主要候选"
    if category == "B":
        return "方向可看，但存在平局/客场/信息确认风险，不适合重仓"
    if category == "C":
        return "数据或盘口支持一般，只能小注尝试或观望"
    if not match.has_complete_odds():
        return "赔率不完整或让球数据缺失，不建议碰"
    if match.has_odds_conflict():
        return "赔率存在冲突，无法确认"
    return "风险过高或数据无法确认，不建议碰"


def _model_and_odds_not_conflicting(match: Match, goal_model: GoalModel) -> bool:
    probs = normalized_probabilities(match.spf_odds)
    if not probs or goal_model.home_win is None or goal_model.away_win is None or goal_model.draw is None:
        return False
    odds_favorite = max(probs, key=probs.get)
    model_probs = {"win": goal_model.home_win, "draw": goal_model.draw, "loss": goal_model.away_win}
    model_favorite = max(model_probs, key=model_probs.get)
    return odds_favorite == model_favorite
