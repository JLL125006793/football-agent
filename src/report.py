"""中文报告渲染。"""

from __future__ import annotations

from src.fetchers.base import FetchSummary
from src.models import Match
from src.odds import format_probability, implied_probabilities, normalized_probabilities
from src.poisson import GoalModel, probability_interval
from src.risk import RiskAssessment
from src.selector import ParlayRecommendation, Pick


def render_report(
    matches: list[Match],
    assessments: dict[str, RiskAssessment],
    goal_models: dict[str, GoalModel],
    recommendation: ParlayRecommendation,
    fetch_summary: FetchSummary,
) -> str:
    lines: list[str] = []
    lines.extend(_render_fetch_status(fetch_summary, matches))
    lines.append("")
    lines.append("【今日竞彩全部比赛初筛表】")
    lines.append("比赛编号 | 开赛时间 | 联赛 | 对阵 | 胜平负赔率 | 让球数 | 让球胜平负赔率 | 数据来源 | 初筛类别 | 风险评分 | 简短理由")
    if not matches:
        lines.append("无法确认 | 无法确认 | 无法确认 | 无法确认 | 无法确认 | 无法确认 | 无法确认 | 无法确认 | D类 | 0 | 不买：无法确认今日官方完整赛程和赔率")
    for match in matches:
        assessment = assessments[match.match_id]
        handicap = "无法确认" if match.handicap is None else f"{match.handicap:g}"
        lines.append(
            " | ".join(
                [
                    match.match_id,
                    match.start_time,
                    match.league,
                    match.matchup,
                    match.spf_odds.display(),
                    handicap,
                    match.rqspf_odds.display(),
                    match.data_source,
                    f"{assessment.category}类",
                    str(assessment.score),
                    assessment.reason,
                ]
            )
        )

    lines.append("")
    lines.append("【赔率概率校验】")
    if not matches:
        lines.append("无法确认：没有可解析的完整比赛赔率数据")
    for match in matches:
        lines.append(f"{match.match_id} {match.matchup}")
        lines.append(f"- 胜平负隐含概率：{_prob_dict(implied_probabilities(match.spf_odds))}")
        lines.append(f"- 胜平负去水概率：{_prob_dict(normalized_probabilities(match.spf_odds))}")
        lines.append(f"- 让球胜平负隐含概率：{_prob_dict(implied_probabilities(match.rqspf_odds))}")
        lines.append(f"- 让球胜平负去水概率：{_prob_dict(normalized_probabilities(match.rqspf_odds))}")

    lines.append("")
    lines.append("【最终唯一二串一推荐】")
    if recommendation.picks is None:
        lines.extend(_render_no_pick(recommendation))
    else:
        lines.extend(_render_pick("比赛1", recommendation.picks[0]))
        lines.append("")
        lines.extend(_render_pick("比赛2", recommendation.picks[1]))
        lines.append("")
        lines.extend(_render_combo(recommendation))

    lines.append("")
    lines.extend(_review_checklist())
    lines.append("")
    lines.append("连错风控：连错3天下一单降到100元；连错5天下一单降到50元或暂停；连错8天必须暂停复盘，不允许加倍追回。")
    lines.append("免责声明：本项目仅做数据分析和风控提示，不承诺命中率，不自动下注，不构成任何赌博保证；严禁使用马丁格尔倍投追回。")
    return "\n".join(lines)


def _render_fetch_status(fetch_summary: FetchSummary, matches: list[Match]) -> list[str]:
    official_sources = "、".join(fetch_summary.official_sources) if fetch_summary.official_sources else "无法确认"
    backup_sources = "、".join(fetch_summary.backup_sources) if fetch_summary.backup_sources else "无法确认"
    failure_reasons = "；".join(fetch_summary.failure_reasons) if fetch_summary.failure_reasons else "无"
    missing = sorted(set(fetch_summary.missing_fields + [field for match in matches for field in match.missing_fields]))
    return [
        "【数据抓取状态】",
        f"查询日期：{fetch_summary.query_date}",
        f"官方数据源：{official_sources}",
        f"备用数据源：{backup_sources}",
        f"抓取是否成功：{'是' if fetch_summary.success else '否'}",
        f"官方数据是否确认：{'是' if fetch_summary.official_confirmed else '否'}",
        f"赔率是否完整：{'是' if fetch_summary.odds_complete else '否'}",
        f"数据冲突情况：{fetch_summary.conflict_note}",
        f"无法确认字段：{','.join(missing) if missing else '无'}",
        f"抓取失败原因：{failure_reasons}",
        f"最终采用数据源：{fetch_summary.selected_source}",
    ]


def _render_pick(title: str, pick: Pick) -> list[str]:
    match = pick.match
    goal_model = pick.goal_model
    support = _support_current_selection(pick)
    return [
        f"{title}：",
        f"编号：{match.match_id}",
        f"对阵：{match.matchup}",
        f"玩法：{pick.market}",
        f"选择：{pick.selection_label}",
        f"赔率：{pick.odds:.2f}",
        f"初筛类别：{pick.assessment.category}类",
        f"风险评分：{pick.assessment.score}",
        f"入选理由：{pick.reason}",
        f"主要风险：{pick.risk}",
        "",
        "进球模型辅助：",
        f"- 主队预期进球：{_number(goal_model.home_expected)}（{goal_model.note}）",
        f"- 客队预期进球：{_number(goal_model.away_expected)}（{goal_model.note}）",
        f"- 主胜概率区间：{probability_interval(goal_model.home_win)}",
        f"- 平局概率区间：{probability_interval(goal_model.draw)}",
        f"- 客胜概率区间：{probability_interval(goal_model.away_win)}",
        f"- 让球胜/平/负概率区间：{probability_interval(goal_model.handicap_win)} / {probability_interval(goal_model.handicap_draw)} / {probability_interval(goal_model.handicap_loss)}",
        f"- 最可能比分：{goal_model.most_likely_score}",
        f"- 单比分概率：{format_probability(goal_model.most_likely_score_probability)}",
        f"- 小比分簇概率：{format_probability(goal_model.low_score_cluster)}",
        f"- 中比分簇概率：{format_probability(goal_model.mid_score_cluster)}",
        f"- 大比分簇概率：{format_probability(goal_model.high_score_cluster)}",
        f"- 是否支持当前选择：{support}",
    ]


def _render_combo(recommendation: ParlayRecommendation) -> list[str]:
    return [
        f"组合总赔率：{recommendation.total_odds:.2f}" if recommendation.total_odds else "组合总赔率：无法确认",
        f"组合质量评级：{recommendation.quality}",
        f"预估命中概率区间：{recommendation.hit_probability_range}",
        f"是否处于主战区3.5–4.2倍：{recommendation.in_main_zone}",
        f"是否存在硬凑赔率：{recommendation.forced_odds}",
        f"是否建议下注：{recommendation.bet_advice}",
        f"建议投入金额：{recommendation.stake}",
        f"如果临场首发不利，必须剔除哪一场：{recommendation.remove_if_lineup_bad}",
        f"如果赔率变化到什么程度就放弃：{recommendation.abandon_if_odds_move}",
        f"最大风险点：{recommendation.max_risk}",
        f"最终一句话结论：{recommendation.conclusion}",
    ]


def _render_no_pick(recommendation: ParlayRecommendation) -> list[str]:
    return [
        "比赛1：无法确认",
        "比赛2：无法确认",
        "组合总赔率：无法确认",
        f"组合质量评级：{recommendation.quality}",
        f"预估命中概率区间：{recommendation.hit_probability_range}",
        f"是否处于主战区3.5–4.2倍：{recommendation.in_main_zone}",
        f"是否存在硬凑赔率：{recommendation.forced_odds}",
        f"是否建议下注：{recommendation.bet_advice}",
        f"建议投入金额：{recommendation.stake}",
        f"如果临场首发不利，必须剔除哪一场：{recommendation.remove_if_lineup_bad}",
        f"如果赔率变化到什么程度就放弃：{recommendation.abandon_if_odds_move}",
        f"最大风险点：{recommendation.max_risk}",
        f"最终一句话结论：{recommendation.conclusion}",
    ]


def _review_checklist() -> list[str]:
    return [
        "【临场30–60分钟复核清单】",
        "1. 首发阵容",
        "2. 主力前锋是否缺阵",
        "3. 门将和中卫是否临时缺阵",
        "4. 赔率是否异常跳动",
        "5. 让球是否变化",
        "6. 是否出现明显造热",
        "7. 是否有临场伤停",
        "8. 是否有大面积轮换",
        "9. 天气是否恶化",
        "10. 如果核心逻辑失效，必须放弃，不要硬买",
    ]


def _prob_dict(probs: dict[str, float] | None) -> str:
    if not probs:
        return "无法确认"
    return f"胜{format_probability(probs.get('win'))} / 平{format_probability(probs.get('draw'))} / 负{format_probability(probs.get('loss'))}"


def _number(value: float | None) -> str:
    if value is None:
        return "无法确认"
    return f"{value:.2f}"


def _support_current_selection(pick: Pick) -> str:
    if pick.model_probability is None:
        return "无法确认"
    if pick.model_probability >= 0.45:
        return "支持"
    if pick.model_probability >= 0.35:
        return "弱支持，需降注"
    return "不支持"
