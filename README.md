# football-agent

`football-agent` 是一个本地运行的 Python 工具，用于**尽量联网自动抓取今日/指定日期竞彩足球赛程与赔率**，并在数据可确认时按风控规则输出唯一二串一方案。项目也保留手动 JSON 兜底模式。

> 重要边界：本项目只做数据分析和风控提示，不保证命中率，不自动下注，不提供赌博保证。程序禁止编造比赛、赔率、让球数、伤停、阵容、xG、战意或天气信息；任何字段无法确认都会写“无法确认”，数据不完整或抓取失败时允许且应该输出“不买”。严禁马丁格尔倍投追回。

## 数据源优先级

程序按以下顺序尝试抓取：

1. **官方公开数据源**
   - `www.sporttery.cn`
   - `sporttery.cn`
   - `www.lottery.gov.cn`
   - `lottery.gov.cn`
2. **备用公开交叉核验数据源**
   - `jc.zhcw.com`
   - `trade.500.com`
   - `www.zgzcw.com`
   - `www.okooo.com`

官方数据优先；如果官方页面无法解析完整赔率，程序会尝试备用公开页面。使用备用数据时，报告会标注“非官方公开数据，临场必须复核”。如果来源之间赔率明显冲突，报告会标注“赔率存在冲突，无法确认”，并降级或不推荐。

## 文件结构

```text
football-agent/
├── main.py
├── requirements.txt
├── README.md
├── config.json
├── data/
│   ├── matches_example.json
│   ├── matches_today.json
│   └── raw/
└── src/
    ├── __init__.py
    ├── models.py
    ├── odds.py
    ├── poisson.py
    ├── selector.py
    ├── risk.py
    ├── report.py
    └── fetchers/
        ├── __init__.py
        ├── base.py
        ├── sporttery.py
        ├── zhcw.py
        ├── fivehundred.py
        ├── zgzcw.py
        ├── okooo.py
        └── fallback.py
```

## 环境要求

- Python 3.10+
- 建议开启 Codex Agent internet access，并允许访问以下域名：
  - `sporttery.cn`
  - `www.sporttery.cn`
  - `lottery.gov.cn`
  - `www.lottery.gov.cn`
  - `jc.zhcw.com`
  - `trade.500.com`
  - `www.zgzcw.com`
  - `www.okooo.com`

安装依赖：

```bash
python -m pip install -r requirements.txt
```

依赖包括 `requests`、`beautifulsoup4`、`lxml`、`python-dateutil`。如果运行环境暂时无法安装依赖，程序仍会使用 Python 标准库尝试联网抓取；但建议安装依赖以提高 HTML 解析兼容性。

## 运行方式

### 1. 联网抓取今日数据

```bash
python main.py --live
```

不传 `--date` 时默认使用当前系统日期。

### 2. 联网抓取指定日期

```bash
python main.py --live --date YYYY-MM-DD
```

例如：

```bash
python main.py --live --date 2026-05-09
```

### 3. 手动数据兜底模式

```bash
python main.py --data data/matches_today.json
```

也可以复制示例文件后手动录入：

```bash
cp data/matches_example.json data/matches_today.json
python main.py --data data/matches_today.json
```

## 联网抓取失败怎么办

如果官方站点反爬、页面结构变化、地区网络限制、DNS/连接失败、数据源返回空数据、赔率字段缺失、让球字段缺失或备用数据与官方数据冲突，程序不会崩溃，也不会编造数据，而是输出：

- 抓取失败原因
- 无法确认字段
- 数据冲突情况
- `D单 / 不买`

原始抓取内容会保存到：

```text
data/raw/YYYY-MM-DD/
```

例如：

```text
data/raw/2026-05-09/sporttery_1.html
```

如果本地环境显示 `Tunnel connection failed: 403 Forbidden`、DNS 错误或连接超时，请检查是否开启 internet access，并确认上述域名允许访问。

## 手动数据字段含义

数据文件顶层必须是数组，每个元素是一场比赛。联网模式会尽量生成 `data/matches_today.json`；手动模式可以直接编辑该文件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `match_id` | string | 比赛编号。 |
| `start_time` | string | 开赛时间。 |
| `league` | string | 联赛名称。 |
| `home_team` | string | 主队。 |
| `away_team` | string | 客队。 |
| `spf_odds` | object | 胜平负赔率，包含 `win` / `draw` / `loss`。 |
| `handicap` | number/null | 让球数；主队让球通常录入负数，受让录入正数。 |
| `rqspf_odds` | object | 让球胜平负赔率，包含 `win` / `draw` / `loss`。 |
| `data_source` | string | 数据来源；备用源会标注非官方。 |
| `official_data_confirmed` | boolean | 是否官方数据确认。 |
| `odds_complete` | boolean | 赔率与让球是否完整。 |
| `fetch_status` | string | 抓取状态，如 `成功` 或失败原因。 |
| `missing_fields` | array | 缺失字段列表。 |
| `odds_conflict_note` | string | 赔率冲突说明，无冲突填 `无`。 |
| `injury_note` | string | 伤停说明；无法获取写 `无法确认`。 |
| `lineup_note` | string | 阵容说明；无法获取写 `无法确认`。 |
| `motivation_note` | string | 战意说明；无法获取写 `无法确认`。 |
| `weather_note` | string | 天气说明；无法获取写 `无法确认`。 |
| `recent_*` | number/null | 近10场进失球数据；无法确认填 `null`。 |
| `home_xg` / `away_xg` / `home_xga` / `away_xga` | number/null | 真实 xG/xGA；没有可靠公开数据填 `null`。 |

## 程序会计算什么

1. 胜平负与让球胜平负隐含概率。
2. 胜平负与让球胜平负去水归一化概率。
3. 单项选择对应赔率、二串一组合赔率、组合概率区间。
4. 泊松进球模型：优先真实 xG/xGA；其次近10场进失球；再其次只用赔率做弱模型估算并标注“模型置信度低”。
5. 主胜/平局/客胜概率区间，让球胜/平/负概率区间，最可能比分，单比分概率，小/中/大比分簇概率。
6. 100 分单场风险评分并分 A/B/C/D 类。
7. 唯一二串一筛选，或在数据不完整/风险过高时输出“不买”。

## 风控规则摘要

- 默认预算：200 元。
- 只做二串一，不自动下注。
- 总赔率优先 3.5–4.2；两场逻辑非常干净时可放宽到 4.2–4.8。
- 不为了凑 5 倍强行选择高风险冷门。
- 避免两个平局、两个高风险客胜、两个高风险让胜、两个盘口异常/数据缺失/赔率冲突比赛相串。
- 低于 70 分不建议入串；70–80 分只能小注尝试；80–88 分可作为候选；88 分以上才可作为核心胆。
- 官方数据无法确认至少扣 15 分；赔率不完整直接 D 类；赔率冲突至少扣 15 分；页面抓取失败不能推荐。
- 连错 3 天下一单降到 100 元；连错 5 天降到 50 元或暂停；连错 8 天必须暂停复盘，不允许加倍追回。
