"""二串一候选选择与组合风控。"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from src.models import Match
from src.odds import LABELS, pick_market_probability
from src.poisson import GoalModel
from src.risk import RiskAssessment


@dataclass(frozen=True)
class Pick:
    match: Match
    market: str
    selection: str
    selection_label: str
    odds: float
    model_probability: float | None
    assessment: RiskAssessment
    goal_model: GoalModel
    reason: str
    risk: str


@dataclass(frozen=True)
class ParlayRecommendation:
    picks: tuple[Pick, Pick] | None
    total_odds: float | None
    quality: str
    hit_probability_range: str
    in_main_zone: str
    forced_odds: str
    bet_advice: str
    stake: str
    remove_if_lineup_bad: str
    abandon_if_odds_move: str
    max_risk: str
    conclusion: str
    no_pick_reason: str | None = None


def select_parlay(
    matches: list[Match],
    assessments: dict[str, RiskAssessment],
    goal_models: dict[str, GoalModel],
    config: dict,
) -> ParlayRecommendation:
    min_matches = int(config.get("min_matches_for_recommendation", 6))
    if not matches:
        return _no_pick("不买：无法确认今日官方完整赛程和赔率")
    if len(matches) < min_matches:
        return _no_pick(f"当天可投注比赛数量不足{min_matches}场，建议放弃")

    complete_matches = [match for match in matches if match.is_data_complete_for_selection()]
    if len(complete_matches) < 2:
        return _no_pick("数据完整且可筛选的比赛不足2场，输出不买/等待数据确认")
    if len(matches) >= min_matches and len(complete_matches) < len(matches):
        return _no_pick("当天场次数量达到强制筛选门槛，但存在数据不完整比赛，不能强行给单")

    picks = [_best_pick(match, assessments[match.match_id], goal_models[match.match_id]) for match in complete_matches]
    picks = [pick for pick in picks if pick is not None and pick.assessment.category in ("A", "B", "C")]
    if len(picks) < 2:
        return _no_pick("没有足够的A/B/C候选，不能硬凑二串一")

    target_min = float(config.get("target_odds_min", 3.5))
    target_max = float(config.get("target_odds_max", 4.2))
    clean_max = float(config.get("clean_logic_odds_max", 4.8))
    candidates: list[tuple[float, tuple[Pick, Pick], float]] = []
    for first, second in combinations(picks, 2):
        if not _pair_allowed(first, second):
            continue
        total_odds = first.odds * second.odds
        if target_min <= total_odds <= target_max:
            zone_penalty = 0
        elif total_odds <= clean_max and first.assessment.category == "A" and second.assessment.category == "A":
            zone_penalty = 0.3
        else:
            zone_penalty = 1.0 + abs(total_odds - ((target_min + target_max) / 2))
        score = first.assessment.score + second.assessment.score - zone_penalty * 20
        candidates.append((score, (first, second), total_odds))

    if not candidates:
        if len(matches) >= 6 and len(complete_matches) == len(matches):
            return _forced_low_quality(picks, target_min, target_max)
        return _no_pick("组合规则过滤后无合格二串一，输出不买/等待数据确认")

    _, chosen, total_odds = max(candidates, key=lambda item: item[0])
    return _build_recommendation(chosen, total_odds, target_min, target_max, forced=False)


def _best_pick(match: Match, assessment: RiskAssessment, goal_model: GoalModel) -> Pick | None:
    if not match.has_complete_odds():
        return None

    market_models = [
        (
            "胜平负",
            match.spf_odds,
            {"win": goal_model.home_win, "draw": goal_model.draw, "loss": goal_model.away_win},
        ),
        (
            "让球胜平负",
            match.rqspf_odds,
            {"win": goal_model.handicap_win, "draw": goal_model.handicap_draw, "loss": goal_model.handicap_loss},
        ),
    ]
    candidates: list[Pick] = []
    for market, odds_set, model_probs in market_models:
        valid = {key: value for key, value in model_probs.items() if value is not None and odds_set.get(key) is not None}
        if not valid:
            continue
        selection = max(valid, key=valid.get)
        odds = odds_set.get(selection)
        if odds is None:
            continue
        market_prob = pick_market_probability(odds_set, selection)
        edge_ok = market_prob is not None and valid[selection] >= market_prob * 0.92
        edge_note = f"模型方向与{market}主方向匹配" if edge_ok else f"{market}模型支持有限，需降注"
        candidates.append(
            Pick(
                match=match,
                market=market,
                selection=selection,
                selection_label=LABELS[selection],
                odds=odds,
                model_probability=valid[selection],
                assessment=assessment,
                goal_model=goal_model,
                reason=edge_note,
                risk="；".join(assessment.risks[:3]),
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda pick: ((pick.model_probability or 0) * 100) + min(pick.odds, 4.8))


def _pair_allowed(first: Pick, second: Pick) -> bool:
    if "A" not in (first.assessment.category, second.assessment.category):
        return False
    if "D" in (first.assessment.category, second.assessment.category):
        return False
    if first.selection == "draw" and second.selection == "draw":
        return False
    if first.selection == "loss" and second.selection == "loss" and min(first.assessment.score, second.assessment.score) < 85:
        return False
    handicap_wins = [pick for pick in (first, second) if pick.market == "让球胜平负" and pick.selection == "win"]
    if len(handicap_wins) == 2 and min(first.assessment.score, second.assessment.score) < 88:
        return False
    blocked_words = ("盘口异常", "战意不明", "轮换严重", "大面积轮换")
    combined_notes = " ".join(
        note
        for pick in (first, second)
        for note in (pick.match.odds_movement_note, pick.match.motivation_note, pick.match.injury_note)
        if note
    )
    return not any(word in combined_notes for word in blocked_words)


def _build_recommendation(chosen: tuple[Pick, Pick], total_odds: float, target_min: float, target_max: float, forced: bool) -> ParlayRecommendation:
    scores = [pick.assessment.score for pick in chosen]
    categories = [pick.assessment.category for pick in chosen]
    probs = [pick.model_probability for pick in chosen if pick.model_probability is not None]
    hit = probs[0] * probs[1] if len(probs) == 2 else None
    hit_range = "无法确认" if hit is None else f"{max(0, hit - 0.04) * 100:.1f}%–{min(1, hit + 0.04) * 100:.1f}%"

    if forced:
        quality = "C单"
        stake = "50–100元，且不建议投满200元"
        advice = "仅可小额娱乐，不建议重仓"
        conclusion = "娱乐单"
    elif all(score >= 85 for score in scores) and max(scores) >= 88 and all(cat == "A" for cat in categories):
        quality = "A单"
        stake = "200元"
        advice = "可按预算上限执行，但仍需临场复核"
        conclusion = "买"
    elif "A" in categories and any(cat in ("B", "A") for cat in categories):
        quality = "B单"
        stake = "100–150元"
        advice = "建议小买/中低仓位"
        conclusion = "小买"
    else:
        quality = "C单"
        stake = "50–100元，且不建议投满200元"
        advice = "组合质量一般，仅可娱乐"
        conclusion = "娱乐单"

    main_zone = "是" if target_min <= total_odds <= target_max else "否"
    forced_odds = "否" if total_odds <= 4.8 else "是"
    weakest = min(chosen, key=lambda pick: pick.assessment.score)
    max_risk = "；".join([pick.risk for pick in chosen if pick.risk]) or "仍需临场复核"
    return ParlayRecommendation(
        picks=chosen,
        total_odds=total_odds,
        quality=quality,
        hit_probability_range=hit_range,
        in_main_zone=main_zone,
        forced_odds=forced_odds,
        bet_advice=advice,
        stake=stake,
        remove_if_lineup_bad=f"优先剔除{weakest.match.match_id} {weakest.match.matchup}",
        abandon_if_odds_move="任一选择赔率临场相对录入值波动超过约10%，或让球方向变化，即放弃",
        max_risk=max_risk,
        conclusion=conclusion,
    )


def _forced_low_quality(picks: list[Pick], target_min: float, target_max: float) -> ParlayRecommendation:
    sorted_picks = sorted(picks, key=lambda pick: pick.assessment.score, reverse=True)
    for first, second in combinations(sorted_picks, 2):
        if "D" not in (first.assessment.category, second.assessment.category):
            return _build_recommendation((first, second), first.odds * second.odds, target_min, target_max, forced=True)
    return _no_pick("即使场次数≥6，也没有可接受的非D类组合")


def _no_pick(reason: str) -> ParlayRecommendation:
    return ParlayRecommendation(
        picks=None,
        total_odds=None,
        quality="D单",
        hit_probability_range="无法确认",
        in_main_zone="无法确认",
        forced_odds="否",
        bet_advice="否，等待数据确认",
        stake="0元",
        remove_if_lineup_bad="无可剔除对象：当前不买",
        abandon_if_odds_move="数据未确认前不下注",
        max_risk=reason,
        conclusion="不买",
        no_pick_reason=reason,
    )
