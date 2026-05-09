"""按官方优先、备用兜底的顺序抓取并合并数据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.fetchers.base import FAIL_CONFLICT, FetchAttempt, FetchSummary
from src.fetchers.fivehundred import FiveHundredFetcher
from src.fetchers.okooo import OkoooFetcher
from src.fetchers.sporttery import SportteryFetcher
from src.fetchers.zhcw import ZhcwFetcher
from src.fetchers.zgzcw import ZgzcwFetcher


def fetch_live_matches(query_date: str, config: dict[str, Any]) -> tuple[list[dict[str, Any]], FetchSummary]:
    """抓取指定日期的竞彩数据。官方完整时优先使用官方，否则尝试备用公开源。"""
    raw_dir = Path(config.get("raw_data_dir", "data/raw")) / query_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    attempts: list[FetchAttempt] = []
    official_fetchers = [SportteryFetcher(config)]
    backup_fetchers = [ZhcwFetcher(config), FiveHundredFetcher(config), ZgzcwFetcher(config), OkoooFetcher(config)]

    official_matches: list[dict[str, Any]] = []
    for fetcher in official_fetchers:
        matches, source_attempts = fetcher.fetch(query_date, raw_dir)
        attempts.extend(source_attempts)
        official_matches.extend(matches)

    selected_matches = _complete_matches(official_matches)
    selected_source = "sporttery/lottery.gov.cn"
    conflict_note = "无"

    backup_matches: list[dict[str, Any]] = []
    if not selected_matches:
        for fetcher in backup_fetchers:
            matches, source_attempts = fetcher.fetch(query_date, raw_dir)
            attempts.extend(source_attempts)
            backup_matches.extend(matches)
            complete = _complete_matches(matches)
            if complete:
                selected_matches = complete
                selected_source = fetcher.source_name
                break

    if official_matches and backup_matches:
        conflict_note = _detect_conflict(official_matches, backup_matches)
        if conflict_note != "无":
            selected_matches = [_mark_conflict(match, conflict_note) for match in selected_matches]

    _write_matches_today(selected_matches)

    missing_fields = sorted({field for match in selected_matches for field in match.get("missing_fields", [])})
    failure_reasons = _failure_reasons(attempts)
    summary = FetchSummary(
        query_date=query_date,
        official_sources=["www.sporttery.cn", "sporttery.cn", "www.lottery.gov.cn", "lottery.gov.cn"],
        backup_sources=["jc.zhcw.com", "trade.500.com", "www.zgzcw.com", "www.okooo.com"],
        attempts=attempts,
        success=bool(selected_matches),
        official_confirmed=bool(selected_matches) and all(match.get("official_data_confirmed") for match in selected_matches),
        odds_complete=bool(selected_matches) and all(match.get("odds_complete") for match in selected_matches),
        conflict_note=conflict_note,
        missing_fields=missing_fields,
        failure_reasons=failure_reasons if failure_reasons else ([] if selected_matches else ["无法确认今日官方完整赛程和赔率"]),
        selected_source=selected_source if selected_matches else "无法确认",
    )
    return selected_matches, summary


def _complete_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [match for match in matches if match.get("odds_complete") and not match.get("missing_fields")]


def _detect_conflict(official_matches: list[dict[str, Any]], backup_matches: list[dict[str, Any]]) -> str:
    official_index = {_team_key(match): match for match in official_matches}
    for backup in backup_matches:
        official = official_index.get(_team_key(backup))
        if not official:
            continue
        for market in ("spf_odds", "rqspf_odds"):
            official_odds = official.get(market) or {}
            backup_odds = backup.get(market) or {}
            for key in ("win", "draw", "loss"):
                left = official_odds.get(key)
                right = backup_odds.get(key)
                if left and right and abs(float(left) - float(right)) >= 0.15:
                    return f"赔率存在冲突，无法确认：{official.get('match_id')} {market}.{key} 官方{left} vs 备用{right}"
    return "无"


def _mark_conflict(match: dict[str, Any], conflict_note: str) -> dict[str, Any]:
    updated = dict(match)
    updated["odds_conflict_note"] = conflict_note
    updated.setdefault("missing_fields", [])
    updated["missing_fields"] = sorted(set(updated["missing_fields"] + ["odds_conflict_note"]))
    return updated


def _team_key(match: dict[str, Any]) -> tuple[str, str]:
    return (str(match.get("home_team", "")).strip(), str(match.get("away_team", "")).strip())


def _failure_reasons(attempts: list[FetchAttempt]) -> list[str]:
    reasons = []
    for attempt in attempts:
        if not attempt.success and attempt.reason not in reasons:
            reasons.append(attempt.reason)
    return reasons


def _write_matches_today(matches: list[dict[str, Any]]) -> None:
    path = Path("data/matches_today.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
