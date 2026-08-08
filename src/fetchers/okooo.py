"""澳客公开页面抓取器。"""

from __future__ import annotations

from src.fetchers.base import BaseFetcher


class OkoooFetcher(BaseFetcher):
    source_name = "okooo"
    official = False

    def urls_for_date(self, query_date: str) -> list[str]:
        return [
            "https://www.okooo.com/jingcai/",
            "https://www.okooo.com/jingcai/shengpingfu/",
        ]
