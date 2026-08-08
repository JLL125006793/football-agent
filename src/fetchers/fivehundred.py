"""500彩票网公开页面抓取器。"""

from __future__ import annotations

from src.fetchers.base import BaseFetcher


class FiveHundredFetcher(BaseFetcher):
    source_name = "500"
    official = False

    def urls_for_date(self, query_date: str) -> list[str]:
        return [
            "https://trade.500.com/jczq/",
            "https://trade.500.com/jczq/?playid=269",
        ]
