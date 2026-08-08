from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.fetchers.base import BaseFetcher, _with_source
from src.models import Match
from src.poisson import GoalModel
from src.risk import RiskAssessment
from src.selector import select_parlay


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
QUERY_DATE = "2026-08-08"


class ParserAndNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetcher = BaseFetcher()

    def test_json_payload_normalizes_aliases_and_odds(self) -> None:
        text = (FIXTURES / "parser_payload.json").read_text(encoding="utf-8")

        matches = self.fetcher.parse_response(text, "application/json", QUERY_DATE)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["match_id"], "周六002")
        self.assertEqual(match["start_time"], "2026-08-08 19:30")
        self.assertEqual(match["league"], "西甲")
        self.assertEqual(match["home_team"], "皇家马德里")
        self.assertEqual(match["away_team"], "巴塞罗那")
        self.assertEqual(match["spf_odds"], {"win": 1.75, "draw": 3.6, "loss": 4.5})
        self.assertEqual(match["handicap"], -1.0)
        self.assertEqual(match["rqspf_odds"], {"win": 3.1, "draw": 3.4, "loss": 2.0})

    def test_html_table_extracts_match_and_handicap(self) -> None:
        html = (FIXTURES / "parser_table.html").read_text(encoding="utf-8")

        matches = self.fetcher.parse_response(html, "text/html", QUERY_DATE)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["match_id"], "周六001")
        self.assertEqual(match["league"], "英超")
        self.assertEqual(match["home_team"], "阿森纳")
        self.assertEqual(match["away_team"], "切尔西")
        self.assertEqual(match["handicap"], -1.0)
        self.assertEqual(match["spf_odds"], {"win": 1.8, "draw": 3.4, "loss": 4.2})
        self.assertEqual(match["rqspf_odds"], {"win": 3.2, "draw": 3.5, "loss": 1.95})

    def test_script_block_extracts_embedded_json(self) -> None:
        html = (FIXTURES / "parser_script.html").read_text(encoding="utf-8")

        matches = self.fetcher.parse_response(html, "text/html", QUERY_DATE)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["match_id"], "周六003")
        self.assertEqual(match["home_team"], "拜仁慕尼黑")
        self.assertEqual(match["away_team"], "多特蒙德")
        self.assertEqual(match["handicap"], 1.0)
        self.assertEqual(match["rqspf_odds"], {"win": 1.25, "draw": 5.0, "loss": 8.0})

    def test_free_text_fallback_extracts_match(self) -> None:
        text = (FIXTURES / "parser_freetext.txt").read_text(encoding="utf-8")

        matches = self.fetcher.parse_response(text, "text/plain", QUERY_DATE)

        self.assertEqual(len(matches), 1)
        match = matches[0]
        self.assertEqual(match["match_id"], "周六004")
        self.assertEqual(match["start_time"], "2026-08-08 21:00")
        self.assertEqual(match["league"], "法甲")
        self.assertEqual(match["home_team"], "巴黎圣日耳曼")
        self.assertEqual(match["away_team"], "里昂")
        self.assertEqual(match["handicap"], -1.0)

    def test_missing_field_detection_marks_incomplete_normalized_match(self) -> None:
        raw = {
            "home_team": "主队",
            "away_team": "客队",
            "spf_odds": {"win": None, "draw": None, "loss": None},
            "rqspf_odds": {"win": None, "draw": None, "loss": None},
        }

        normalized = self.fetcher.parse_response(json.dumps(raw, ensure_ascii=False), "application/json", QUERY_DATE)
        enriched = _with_source(normalized[0], "fixture", official=False)

        self.assertFalse(enriched["odds_complete"])
        self.assertEqual(
            enriched["missing_fields"],
            ["handicap", "league", "match_id", "rqspf_odds", "spf_odds"],
        )

    def test_example_selection_is_deterministic(self) -> None:
        raw_matches = json.loads((FIXTURES / "selection_example.json").read_text(encoding="utf-8"))
        matches = [Match.from_dict(item) for item in raw_matches]
        assessments = {
            "选择001": RiskAssessment(92, "A", "fixture", [], {}),
            "选择002": RiskAssessment(90, "A", "fixture", [], {}),
            "选择003": RiskAssessment(82, "B", "fixture", [], {}),
        }
        goal_models = {
            "选择001": self._goal_model(0.65),
            "选择002": self._goal_model(0.60),
            "选择003": self._goal_model(0.55),
        }
        config = {
            "min_matches_for_recommendation": 3,
            "target_odds_min": 3.5,
            "target_odds_max": 4.2,
            "clean_logic_odds_max": 4.8,
        }

        recommendations = [select_parlay(matches, assessments, goal_models, config) for _ in range(3)]

        self.assertTrue(all(item == recommendations[0] for item in recommendations))
        self.assertIsNotNone(recommendations[0].picks)
        self.assertEqual(
            tuple(pick.match.match_id for pick in recommendations[0].picks or ()),
            ("选择001", "选择002"),
        )
        self.assertAlmostEqual(recommendations[0].total_odds or 0, 3.8)

    @staticmethod
    def _goal_model(home_win: float) -> GoalModel:
        return GoalModel(
            home_expected=1.6,
            away_expected=1.0,
            note="fixture",
            home_win=home_win,
            draw=0.22,
            away_win=1.0 - home_win - 0.22,
            handicap_win=0.40,
            handicap_draw=0.30,
            handicap_loss=0.30,
            most_likely_score="1-0",
            most_likely_score_probability=0.15,
            low_score_cluster=0.50,
            mid_score_cluster=0.35,
            high_score_cluster=0.15,
        )


if __name__ == "__main__":
    unittest.main()
