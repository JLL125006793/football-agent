"""抓取器基础设施与通用解析工具。"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


FAIL_NETWORK = "网络不可达"
FAIL_DNS = "DNS 或连接失败"
FAIL_ANTI_BOT = "官方页面反爬"
FAIL_STRUCTURE = "页面结构变化"
FAIL_NO_MATCH = "日期无比赛"
FAIL_ODDS_MISSING = "赔率字段缺失"
FAIL_HANDICAP_MISSING = "让球字段缺失"
FAIL_EMPTY = "数据源返回空数据"
FAIL_CONFLICT = "备用数据与官方数据冲突"


@dataclass(frozen=True)
class FetchAttempt:
    """单个 URL 的抓取结果。"""

    source: str
    url: str
    official: bool
    success: bool
    reason: str
    raw_path: str | None = None
    matches_count: int = 0


@dataclass(frozen=True)
class FetchSummary:
    """报告层使用的数据抓取摘要。"""

    query_date: str
    official_sources: list[str] = field(default_factory=list)
    backup_sources: list[str] = field(default_factory=list)
    attempts: list[FetchAttempt] = field(default_factory=list)
    success: bool = False
    official_confirmed: bool = False
    odds_complete: bool = False
    conflict_note: str = "无"
    missing_fields: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    selected_source: str = "无法确认"

    @classmethod
    def manual(cls, query_date: str, matches_count: int) -> "FetchSummary":
        return cls(
            query_date=query_date,
            official_sources=["手动录入"],
            success=matches_count > 0,
            official_confirmed=False,
            odds_complete=False,
            conflict_note="手动模式未做联网交叉核验",
            missing_fields=["联网官方确认状态"],
            failure_reasons=[] if matches_count > 0 else [FAIL_EMPTY],
            selected_source="手动录入",
        )


class BaseFetcher:
    """所有抓取器的基类。先保存原始内容，再解析页面。"""

    source_name = "base"
    official = False
    timeout = 15

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; football-agent/2.0; +https://example.invalid)",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        self.requests = importlib.import_module("requests") if importlib.util.find_spec("requests") else None

    def urls_for_date(self, query_date: str) -> list[str]:
        raise NotImplementedError

    def fetch(self, query_date: str, raw_dir: Path) -> tuple[list[dict[str, Any]], list[FetchAttempt]]:
        matches: list[dict[str, Any]] = []
        attempts: list[FetchAttempt] = []
        for index, url in enumerate(self.urls_for_date(query_date), start=1):
            raw_path: Path | None = None
            try:
                text, content_type, status_code = self._get_url(url)
                suffix = ".json" if _looks_json(text, content_type) else ".html"
                raw_path = raw_dir / f"{self.source_name}_{index}{suffix}"
                raw_path.write_text(text, encoding="utf-8", errors="ignore")
                if status_code in (401, 403, 418, 429):
                    attempts.append(self._attempt(url, False, FAIL_ANTI_BOT, raw_path, 0))
                    continue
                if status_code >= 400:
                    attempts.append(self._attempt(url, False, f"网络不可达：HTTP {status_code}", raw_path, 0))
                    continue
                parsed = self.parse_response(text, content_type, query_date)
                parsed = [_with_source(item, self.source_name, self.official) for item in parsed]
                matches.extend(parsed)
                reason = "成功" if parsed else FAIL_EMPTY
                attempts.append(self._attempt(url, bool(parsed), reason, raw_path, len(parsed)))
            except TimeoutError as exc:
                attempts.append(self._attempt(url, False, f"{FAIL_NETWORK}：请求超时：{exc}", raw_path, 0))
            except HTTPError as exc:
                reason = FAIL_ANTI_BOT if exc.code in (401, 403, 418, 429) else f"网络不可达：HTTP {exc.code}"
                attempts.append(self._attempt(url, False, reason, raw_path, 0))
            except (ConnectionError, URLError) as exc:
                attempts.append(self._attempt(url, False, f"{FAIL_DNS}：{exc}", raw_path, 0))
            except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
                attempts.append(self._attempt(url, False, f"{FAIL_STRUCTURE}：{exc}", raw_path, 0))
        return _dedupe_matches(matches), attempts

    def _get_url(self, url: str) -> tuple[str, str, int]:
        if self.requests is not None:
            response = self.requests.get(url, headers=self.headers, timeout=self.timeout)
            return response.text, response.headers.get("content-type", ""), response.status_code
        request = Request(url, headers=self.headers)
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="ignore"), content_type, response.status

    def parse_response(self, text: str, content_type: str, query_date: str) -> list[dict[str, Any]]:
        if _looks_json(text, content_type):
            payload = json.loads(text)
            return _extract_matches_from_payload(payload, query_date)
        return self.parse_html(text, query_date)

    def parse_html(self, html: str, query_date: str) -> list[dict[str, Any]]:
        matches = _extract_matches_with_bs4(html, query_date)
        if not matches:
            matches = _extract_matches_from_tables(html, query_date)
        if matches:
            return matches
        for script_text in _extract_script_text(html):
            for payload in _extract_json_objects(script_text):
                matches.extend(_extract_matches_from_payload(payload, query_date))
        if matches:
            return _dedupe_matches(matches)
        return _extract_matches_from_text(html, query_date)

    def _attempt(self, url: str, success: bool, reason: str, raw_path: Path | None, matches_count: int) -> FetchAttempt:
        return FetchAttempt(
            source=self.source_name,
            url=url,
            official=self.official,
            success=success,
            reason=reason,
            raw_path=str(raw_path) if raw_path else None,
            matches_count=matches_count,
        )


def _looks_json(text: str, content_type: str) -> bool:
    stripped = text.lstrip()
    return "json" in content_type.lower() or stripped.startswith("{") or stripped.startswith("[")


def _with_source(match: dict[str, Any], source: str, official: bool) -> dict[str, Any]:
    match.setdefault("data_source", source if official else f"{source}（非官方公开数据，临场必须复核）")
    match.setdefault("official_data_confirmed", official)
    match.setdefault("fetch_status", "成功")
    match.setdefault("injury_note", "无法确认")
    match.setdefault("lineup_note", "无法确认")
    match.setdefault("motivation_note", "无法确认")
    match.setdefault("weather_note", "无法确认")
    match.setdefault("odds_conflict_note", "无")
    match.setdefault("odds_movement_note", "无法确认")
    match.setdefault("lineup_confirmed", False)
    match.setdefault("home_xg", None)
    match.setdefault("away_xg", None)
    match.setdefault("home_xga", None)
    match.setdefault("away_xga", None)
    match.setdefault("recent_home_goals_for", None)
    match.setdefault("recent_home_goals_against", None)
    match.setdefault("recent_away_goals_for", None)
    match.setdefault("recent_away_goals_against", None)
    match["odds_complete"] = _odds_complete(match)
    match["missing_fields"] = _missing_match_fields(match)
    return match


def _missing_match_fields(match: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field_name in ("match_id", "start_time", "league", "home_team", "away_team"):
        if not match.get(field_name) or str(match.get(field_name)).strip() == "无法确认":
            missing.append(field_name)
    if not _odds_set_complete(match.get("spf_odds")):
        missing.append("spf_odds")
    if match.get("handicap") is None:
        missing.append("handicap")
    if not _odds_set_complete(match.get("rqspf_odds")):
        missing.append("rqspf_odds")
    return sorted(set(missing + list(match.get("missing_fields") or [])))


def _odds_complete(match: dict[str, Any]) -> bool:
    return _odds_set_complete(match.get("spf_odds")) and _odds_set_complete(match.get("rqspf_odds")) and match.get("handicap") is not None


def _odds_set_complete(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return all(_to_float(value.get(key)) is not None and _to_float(value.get(key)) > 1 for key in ("win", "draw", "loss"))


def _extract_matches_from_payload(payload: Any, query_date: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        normalized = _normalize_match_dict(payload, query_date)
        if normalized:
            found.append(normalized)
        for value in payload.values():
            found.extend(_extract_matches_from_payload(value, query_date))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_extract_matches_from_payload(item, query_date))
    return _dedupe_matches(found)


def _normalize_match_dict(raw: dict[str, Any], query_date: str) -> dict[str, Any] | None:
    home = _first(raw, "home_team", "homeTeam", "homeName", "h_cn", "hname", "homesxname")
    away = _first(raw, "away_team", "awayTeam", "guestName", "awayName", "a_cn", "gname", "awaysxname")
    if not home or not away:
        return None

    match_id = _first(raw, "match_id", "matchNum", "matchNo", "num", "serial", "matchCode", "id") or "无法确认"
    league = _first(raw, "league", "leagueName", "l_cn", "league_name") or "无法确认"
    start_time = _first(raw, "start_time", "matchDate", "matchTime", "time", "date") or query_date
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", str(start_time)):
        start_time = f"{query_date} {str(start_time)[:5]}"

    spf = _extract_odds(raw, ("spf", "had", "hhad"), handicap=False)
    rqspf = _extract_odds(raw, ("rqspf", "had_rq", "hhad"), handicap=True)
    handicap = _extract_handicap(raw)
    return {
        "match_id": str(match_id),
        "start_time": str(start_time),
        "league": str(league),
        "home_team": str(home),
        "away_team": str(away),
        "spf_odds": spf,
        "handicap": handicap,
        "rqspf_odds": rqspf,
    }


def _extract_odds(raw: dict[str, Any], containers: tuple[str, ...], handicap: bool) -> dict[str, float | None]:
    candidates: list[Any] = [raw]
    wf = raw.get("wf")
    if isinstance(wf, dict):
        candidates.extend(wf.get(name) for name in containers if isinstance(wf.get(name), dict))
    candidates.extend(raw.get(name) for name in containers if isinstance(raw.get(name), dict))

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        win = _to_float(_first(candidate, "win", "h", "h1", "had_h", "sp3", "odds3"))
        draw = _to_float(_first(candidate, "draw", "d", "h2", "had_d", "sp1", "odds1"))
        loss = _to_float(_first(candidate, "loss", "a", "h3", "had_a", "sp0", "odds0"))
        if isinstance(candidate.get("h1"), dict):
            win = _to_float(candidate["h1"].get("z"))
        if isinstance(candidate.get("h2"), dict):
            draw = _to_float(candidate["h2"].get("z"))
        if isinstance(candidate.get("h3"), dict):
            loss = _to_float(candidate["h3"].get("z"))
        if win and draw and loss:
            return {"win": win, "draw": draw, "loss": loss}
    return {"win": None, "draw": None, "loss": None}


def _extract_handicap(raw: dict[str, Any]) -> float | None:
    value = _first(raw, "handicap", "rq", "rqs", "rfrq", "rfrqz", "letBall", "goalline")
    if isinstance(value, str):
        value = value.replace("让", "").replace("球", "")
    return _to_float(value)


def _find_handicap(text: str) -> float | None:
    labelled = re.search(r"(?:让球|让)\s*([+-]?\d+(?:\.\d+)?)", text)
    if labelled:
        return _to_float(labelled.group(1))
    signed = re.search(r"(?<![\d.])([+-]\d+(?:\.\d+)?)(?![\d.])", text)
    return _to_float(signed.group(1)) if signed else None


def _extract_matches_with_bs4(html: str, query_date: str) -> list[dict[str, Any]]:
    if not importlib.util.find_spec("bs4"):
        return []
    bs4 = importlib.import_module("bs4")
    soup = bs4.BeautifulSoup(html, "lxml")
    rows = []
    for row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return _extract_matches_from_cell_rows(rows, query_date)


def _extract_matches_from_tables(html: str, query_date: str) -> list[dict[str, Any]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL)
    cell_rows = [
        [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cell)).strip() for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL)]
        for row in rows
    ]
    return _extract_matches_from_cell_rows(cell_rows, query_date)


def _extract_matches_from_text(text: str, query_date: str) -> list[dict[str, Any]]:
    plain = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    plain = re.sub(r"<style[^>]*>.*?</style>", " ", plain, flags=re.IGNORECASE | re.DOTALL)
    plain = re.sub(r"<[^>]+>", " ", plain)
    cell_rows = [line.split() for line in plain.splitlines() if "VS" in line.upper()]
    return _extract_matches_from_cell_rows(cell_rows, query_date)


def _extract_matches_from_cell_rows(cell_rows: list[list[str]], query_date: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for cells in cell_rows:
        text = " ".join(cells)
        if len(cells) < 7 or "VS" not in text.upper():
            continue
        odds = [_to_float(token) for token in re.findall(r"(?<!\d)(?:[1-9]\d?|0)\.\d{2}(?!\d)", text)]
        if len(odds) < 6:
            continue
        teams = re.split(r"\s+VS\s+|\s+vs\s+", text, maxsplit=1)
        if len(teams) != 2:
            continue
        left_tokens = teams[0].split()
        right_tokens = teams[1].split()
        matches.append(
            {
                "match_id": _find_match_id(text),
                "start_time": _find_datetime(text, query_date),
                "league": left_tokens[-2] if len(left_tokens) >= 2 else "无法确认",
                "home_team": left_tokens[-1] if left_tokens else "无法确认",
                "away_team": right_tokens[0] if right_tokens else "无法确认",
                "spf_odds": {"win": odds[0], "draw": odds[1], "loss": odds[2]},
                "handicap": _find_handicap(text),
                "rqspf_odds": {"win": odds[3], "draw": odds[4], "loss": odds[5]},
            }
        )
    return _dedupe_matches(matches)


def _extract_script_text(html: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)


def _extract_json_objects(text: str) -> list[Any]:
    payloads: list[Any] = []
    for match in re.finditer(r"(?P<json>\{[^<>]{50,}\}|\[[^<>]{50,}\])", text, flags=re.DOTALL):
        candidate = match.group("json")
        try:
            payloads.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return payloads


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        value = value.get("z") or value.get("value")
    try:
        return float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def _find_match_id(text: str) -> str:
    match = re.search(r"周[一二三四五六日]\d{3}|\d{3,6}", text)
    return match.group(0) if match else "无法确认"


def _find_datetime(text: str, query_date: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}:\d{2}", text)
    if not match:
        return query_date
    value = match.group(0)
    if len(value) == 5:
        return f"{query_date} {value}"
    return value


def _dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for match in matches:
        key = (str(match.get("match_id")), str(match.get("home_team")), str(match.get("away_team")))
        deduped[key] = match
    return list(deduped.values())


def source_host(url: str) -> str:
    return urlparse(url).netloc
