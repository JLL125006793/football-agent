"""官方数据源抓取器：sporttery.cn / lottery.gov.cn。"""

from __future__ import annotations

from src.fetchers.base import BaseFetcher


class SportteryFetcher(BaseFetcher):
    """抓取官方公开页面；不假定隐藏接口存在。"""

    source_name = "sporttery"
    official = True

    def urls_for_date(self, query_date: str) -> list[str]:
        return [
            "https://www.sporttery.cn/",
            "https://www.sporttery.cn/jc/",
            "https://www.sporttery.cn/jc/zqsgkj/",
            "https://www.lottery.gov.cn/",
        ]
