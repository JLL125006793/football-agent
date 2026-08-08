"""命令行入口：竞彩足球二串一筛选与风控。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from src.fetchers.base import FetchSummary
from src.fetchers.fallback import fetch_live_matches
from src.models import Match
from src.poisson import build_goal_model
from src.report import render_report
from src.risk import assess_match
from src.selector import select_parlay


DEFAULT_CONFIG = {
    "daily_budget": 200,
    "target_odds_min": 3.5,
    "target_odds_max": 4.2,
    "clean_logic_odds_max": 4.8,
    "max_goals": 8,
    "min_matches_for_recommendation": 6,
    "raw_data_dir": "data/raw",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="竞彩足球二串一筛选与风控工具")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="联网抓取今日/指定日期竞彩数据")
    mode.add_argument("--data", help="matches.json 手动数据文件路径")
    parser.add_argument("--date", help="查询日期，格式 YYYY-MM-DD；不传则使用当前日期")
    parser.add_argument("--config", default="config.json", help="配置文件路径，默认 config.json")
    args = parser.parse_args()

    config = _load_config(Path(args.config))
    query_date = _resolve_query_date(args.date)

    if args.live:
        raw_matches, fetch_summary = fetch_live_matches(query_date, config)
        matches = [Match.from_dict(item) for item in raw_matches]
    else:
        matches = _load_matches(Path(args.data))
        fetch_summary = FetchSummary.manual(query_date=query_date, matches_count=len(matches))

    max_goals = int(config.get("max_goals", 8))
    goal_models = {match.match_id: build_goal_model(match, max_goals=max_goals) for match in matches}
    assessments = {match.match_id: assess_match(match, goal_models[match.match_id]) for match in matches}
    recommendation = select_parlay(matches, assessments, goal_models, config)
    print(render_report(matches, assessments, goal_models, recommendation, fetch_summary))
    return 0


def _resolve_query_date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    return date.fromisoformat(value).isoformat()


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    with path.open("r", encoding="utf-8") as file:
        loaded = json.load(file)
    return {**DEFAULT_CONFIG, **loaded}


def _load_matches(path: Path) -> list[Match]:
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在：{path}")
    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, list):
        raise ValueError("数据文件顶层必须是比赛数组")
    return [Match.from_dict(item) for item in raw]


if __name__ == "__main__":
    raise SystemExit(main())
