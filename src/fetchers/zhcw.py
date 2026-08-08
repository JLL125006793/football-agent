"""中彩网公开数据源抓取器。"""

from __future__ import annotations

from src.fetchers.base import BaseFetcher


class ZhcwFetcher(BaseFetcher):
    source_name = "zhcw"
    official = False

    def urls_for_date(self, query_date: str) -> list[str]:
        return [
            "https://jc.zhcw.com/?act=zqjsq_spf",
            "https://jc.zhcw.com/",
        ]
