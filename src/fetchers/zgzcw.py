"""中国足彩网公开页面抓取器。"""

from __future__ import annotations

from src.fetchers.base import BaseFetcher


class ZgzcwFetcher(BaseFetcher):
    source_name = "zgzcw"
    official = False

    def urls_for_date(self, query_date: str) -> list[str]:
        return [
            "https://www.zgzcw.com/",
            "https://www.zgzcw.com/jc/",
        ]
