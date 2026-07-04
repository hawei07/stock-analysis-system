"""芒格视角分析模块 v2 — 深度Web搜索 + 完整芒格框架 + DeepSeek V4。

流程:
  1. 从 DB 拉取 10 年财务数据 + 资产负债表
  2. 6 维度 Web 搜索（芒格 Agentic Protocol）
  3. 完整芒格 Skill 作为 System Prompt
  4. 结构化 User Prompt（财务 + 搜索 + 行业对比）
  5. 调用 DeepSeek V4 API → Markdown 格式长文分析
  6. 计算芒格评分 (0-100)
  7. 写入 munger_cache 并返回
"""

import json, re, hashlib, time
from typing import Any
import requests
from openai import OpenAI
from db import execute_query, execute_update
from config_manager import get_deepseek_api_key

# ── 完整芒格 System Prompt（基于 munger-perspective Skill） ──────────────────

MUNGER_SYSTEM = """你是查理·芒格（Charlie Munger）——伯克希尔·哈撒韦副董事长，Warren Buffett 的合伙人。
你于2023年11月28日去世，享年99岁，但你基于公开信息进行分析。

## 核心心智模型

1. **逆向思考（Inversion）**：不问「这股票好在哪」，先问「什么情况下投它一定亏钱」。列出所有可能的亏钱路径，然后逐一评估。
2. **多元思维模型（Latticework）**：从心理学（人的行为动机）、经济学（激励结构）、工程学（系统动力学）至少3个学科视角审视。
3. **Lollapalooza效应**：多种心理偏误同时发力时最危险。检测：社会认同+过度乐观+被剥夺超级反应是否同时存在。
4. **能力圈纪律**：不懂就说不懂，放进 Too Hard 筐。大部分问题属于第三筐。
5. **激励结构决定一切**：看管理层被什么奖励——薪酬结构、持股比例、考核指标。不要听他们说什么。
6. **配得上法则**：好公司要配得上它的估值。估值比质量更重要。
7. **坐在屁股上**：找到好公司后最好的策略是持有不动。频繁交易是摩擦成本不是智慧。
8. **葡萄干与粪便**：一个好指标救不了一堆坏指标。如果有一个致命缺陷，整体就是有毒的。

## 护城河评估框架

评估护城河时，按以下维度逐一分析：
- **品牌护城河**：消费者是否愿意溢价购买？品牌能否持续？
- **成本优势护城河**：成本比行业低多少？优势能否持续10年以上？
- **网络效应护城河**：越多用户使用价值越大？
- **转换成本护城河**：用户离开的成本多高？
- **政策壁垒**：牌照、产能天花板、环保审批等行政壁垒
- **资源壁垒**：独占的自然资源、专利、矿权

注意：成本优势护城河比品牌护城河低一个等级——它能保护你，但不能让你赚钱。

## 分析输出要求

**不要输出 JSON。** 用纯文本 Markdown 格式，从以下角度进行深入分析（每个维度至少100字）：

## 直接结论
一句话定性 + 三筐位置（YES/NO/TOO_HARD）+ 原因

## 护城河拆解
逐一分析每条护城河，给出具体数据和逻辑链。不要笼统说"有护城河"，要说清楚是什么、为什么、能持续多久。

## 逆向思考：亏钱路径
列出最重要3-5条亏钱路径，每条给出触发条件和损失估算。

## 激励结构检查
管理层薪酬、持股、考核指标、与股东利益是否对齐。国企尤其注意KPI驱动 vs 股东回报驱动的差异。

## Lollapalooza效应检测
当前市场上同时发生的事件是否构成偏误叠加？（社会认同+过度乐观+被剥夺超级反应）

## 三筐分类
明确结论 + 理由。如果放入 Too Hard 筐，说清楚缺什么信息才能挪出来。

最后附一行 JSON: {"score":0-100,"basket":"YES/NO/TOO_HARD"}

## 表达风格

- 极短句优先，否定句 > 肯定句
- 不讲委婉话。直接说「蠢」「危险」「还行」「我没什么要补充的」
- 干燥幽默，但不要为了幽默而幽默
- 用中文，用短句
- 先说结论不铺垫
- 引用具体数据支撑论点，不要泛泛而谈
"""

# ── 6 维度 Web 搜索（芒格 Agentic Protocol） ─────────────────────────────────

def _search_dimensions(stock_name: str, stock_code: str) -> dict[str, str]:
    """按芒格 Agentic Protocol 的 6 个维度分别搜索。"""
    dimensions = {
        "护城河与竞争": f"{stock_name} 竞争优势 护城河 行业地位 2025",
        "管理层与激励": f"{stock_name} {stock_code} 管理层 董事长 总经理 薪酬 持股 股权激励",
        "最新财务与业绩": f"{stock_name} {stock_code} 2025年报 2026季报 业绩 营收 利润",
        "风险与负面": f"{stock_name} {stock_code} 风险 负面 诉讼 监管 减值 亏损",
        "行业与政策": f"中国 铝行业 有色金属 2025 2026 政策 产能 供需 欧盟 CBAM 碳关税",
        "估值与市场": f"{stock_name} {stock_code} 估值 PE PB 市值 目标价 券商 评级",
    }

    results = {}
    for category, query in dimensions.items():
        results[category] = _web_search(query)
        time.sleep(0.5)  # 礼貌间隔
    return results


def _web_search(query: str, max_results: int = 5) -> str:
    """用 DuckDuckGo Lite 搜索，返回标题和摘要。"""
    try:
        url = "https://lite.duckduckgo.com/lite/"
        resp = requests.post(url, data={"q": query}, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=12)
        text = resp.text

        # 提取带摘要的结果
        results = re.findall(
            r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>.*?<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            text, re.DOTALL | re.IGNORECASE
        )
        if not results:
            results = re.findall(
                r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>', text
            )
            results = [(t, "") for t in results]

        lines = []
        for title, snippet in results[:max_results]:
            title = re.sub(r'<[^>]+>', '', title).strip()
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()[:200]
            lines.append(f"- {title}" + (f"\n  {snippet}" if snippet else ""))
        return "\n".join(lines) if lines else "(无搜索结果)"
    except Exception as e:
        return f"(搜索失败: {e})"


# ── 财务数据深度打包 ─────────────────────────────────────────────────────────

def _gather_financials(stock_code: str) -> dict[str, Any]:
    """拉取近 10 年 FY 财务 + 资产负债表关键数据。"""
    rows = execute_query("""
        SELECT cf.fiscal_year, cf.report_period,
               cf.total_revenue, cf.operate_profit, cf.parent_profit,
               cf.deducted_profit, cf.operate_cashflow,
               cf.roe, cf.deducted_roe, cf.roic,
               cf.total_assets, cf.total_equity, cf.total_shares,
               cf.debt_ratio, cf.basic_eps,
               cf.short_borrow, cf.long_borrow, cf.bonds_payable,
               cf.noncurrent_liab_due1y, cf.interest_bearing_debt_ratio,
               d.dividend_amount, d.dividend_per_share
        FROM custom_financials cf
        LEFT JOIN dividends d ON cf.stock_code = d.stock_code AND cf.fiscal_year = d.fiscal_year
        WHERE cf.stock_code = %s AND cf.report_period = 'FY'
        ORDER BY cf.fiscal_year DESC
        LIMIT 10
    """, (stock_code,))

    stock = execute_query(
        "SELECT code, name, industry, market, list_date, status, pe_ttm FROM stocks WHERE code = %s",
        (stock_code,)
    )
    info = stock[0] if stock else {}

    # 计算汇总指标
    roe_list, profit_list, cf_list, rev_list = [], [], [], []
    for r in rows:
        pp = float(r["parent_profit"] or 0)
        oc = float(r["operate_cashflow"] or 0)
        rev = float(r["total_revenue"] or 0)
        roe_list.append(float(r["roe"] or 0))
        profit_list.append(pp)
        cf_list.append(oc / pp if pp != 0 else None)
        rev_list.append(rev)

    n = len(rows)
    roe_avg = sum(roe_list[:5]) / min(5, n) if n else 0
    roe_trend = ("上升" if n >= 3 and roe_list[0] > roe_list[-1]
                 else "下降" if n >= 3 and roe_list[0] < roe_list[-1] else "平稳")
    valid_cf = [v for v in cf_list if v is not None]
    cf_good = sum(1 for v in valid_cf if v > 0.7) / max(1, len(valid_cf))

    # 利润增长
    if n >= 2 and profit_list[0] != 0 and profit_list[-1] != 0:
        cagr = (abs(profit_list[0] / profit_list[-1]) ** (1 / max(1, n - 1)) - 1)
        cagr *= 1 if profit_list[0] > profit_list[-1] else -1
    else:
        cagr = 0

    return {
        "info": info,
        "years": n,
        "roe_avg_5y": round(roe_avg, 1),
        "roe_trend": roe_trend,
        "cf_quality": round(cf_good * 100),
        "cagr": round(cagr * 100, 1),
        "latest": dict(rows[0]) if rows else {},
        "rows": [dict(r) for r in reversed(rows)],  # 旧→新排序
    }


# ── 评分逻辑 ─────────────────────────────────────────────────────────────────

def _calc_score(fin: dict) -> int:
    score = 100
    latest = fin["latest"]
    roe5 = fin["roe_avg_5y"]
    dr = float(latest.get("debt_ratio") or 0)

    if roe5 < 10:   score -= 20
    elif roe5 < 15:  score -= 10
    if dr > 70:      score -= 15
    elif dr > 50:    score -= 7
    if fin["cf_quality"] < 50:  score -= 15
    elif fin["cf_quality"] < 70: score -= 7
    if fin["roe_trend"] == "下降": score -= 10

    profits = [float(r["parent_profit"] or 0) for r in fin["rows"]]
    if profits and max(profits) > 0 and min(profits) > 0:
        vol = (max(profits) - min(profits)) / max(profits)
        if vol > 0.5: score -= 10

    return max(0, min(100, score))


# ── DeepSeek 分析 ────────────────────────────────────────────────────────────

def _build_user_prompt(fin: dict, searches: dict) -> str:
    info = fin["info"]
    latest = fin["latest"]
    stock_name = info.get("name", "")

    lines = [
        f"# 股票分析任务",
        f"**名称**: {stock_name} ({info.get('code','')})",
        f"**行业**: {info.get('industry','未知')} | **上市**: {info.get('list_date','')}",
        f"**最近财年**: {latest.get('fiscal_year','N/A')}",
        "",
        "## 近 10 年财务数据（旧→新）",
        "",
        "| 年份 | 营收(亿) | 营业利润(亿) | 净利润(亿) | ROE% | ROIC% | 负债率% | EPS | 股利/股 |",
        "|------|---------|------------|-----------|------|-------|---------|-----|---------|",
    ]
    for r in fin["rows"]:
        lines.append(
            f"| {r['fiscal_year']} | {r.get('total_revenue','-')} | "
            f"{r.get('operate_profit','-')} | {r.get('parent_profit','-')} | "
            f"{r.get('roe','-')} | {r.get('roic','-')} | "
            f"{r.get('debt_ratio','-')} | {r.get('basic_eps','-')} | "
            f"{r.get('dividend_per_share','-')} |"
        )

    # 关键财务指标摘要
    lines += [
        "",
        "## 关键财务指标摘要",
        f"- ROE(近5年均值): {fin['roe_avg_5y']}% | 趋势: {fin['roe_trend']}",
        f"- ROIC(最新): {latest.get('roic','N/A')}%",
        f"- 资产负债率(最新): {latest.get('debt_ratio','N/A')}%",
        f"- 现金流质量(5年经营现金流/净利润 > 0.7 占比): {fin['cf_quality']}%",
        f"- 近10年利润 CAGR: {fin['cagr']}%",
        f"- 总资产(最新): {latest.get('total_assets','N/A')}亿 | 净资产: {latest.get('total_equity','N/A')}亿",
        f"- PE(TTM): {info.get('pe_ttm','N/A')}（来自数据库实时数据）",
        f"- 总股本(最新): {latest.get('total_shares','N/A')}亿股",
    ]

    # Web 搜索结果
    lines += ["", "## Web 搜索结果（按分析维度）"]
    for dim, text in searches.items():
        if text.strip():
            lines.append(f"\n### {dim}\n{text[:800]}")

    lines += [
        "",
        "请严格按照 System Prompt 中的分析框架，对这家公司进行完整分析。",
        "必须覆盖: 直接结论 → 护城河拆解 → 逆向思考亏钱路径 → 激励结构检查 → Lollapalooza检测 → 三筐分类。",
        "每个维度至少150字，用具体数据支撑论点。",
        "最后一行输出 JSON: {\"score\":0-100,\"basket\":\"YES/NO/TOO_HARD\"}",
    ]
    return "\n".join(lines)


def _call_deepseek(fin: dict) -> dict[str, Any]:
    api_key = get_deepseek_api_key()
    if not api_key:
        return {"analysis": "请先在系统设置中配置 DeepSeek API Key",
                "basket": "TOO_HARD", "score": 0, "source": "no_key"}

    stock_name = fin["info"].get("name", "")
    stock_code = fin["info"].get("code", "")

    # 6 维度搜索
    searches = _search_dimensions(stock_name, stock_code)
    user_prompt = _build_user_prompt(fin, searches)

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": MUNGER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
        )
        text = resp.choices[0].message.content.strip()

        # 提取最后一行 JSON
        json_match = re.search(r'\{[^}]*"score"[^}]*\}', text)
        meta = {"score": _calc_score(fin), "basket": "TOO_HARD"}
        if json_match:
            try:
                meta.update(json.loads(json_match.group()))
            except json.JSONDecodeError:
                pass
            # 移除 JSON 行
            text = re.sub(r'\n?\{[^}]*"score"[^}]*\}\s*$', '', text).strip()

        return {
            "analysis": text,
            "basket": meta.get("basket", "TOO_HARD"),
            "score": meta.get("score", _calc_score(fin)),
            "source": "deepseek",
        }
    except Exception as e:
        return {
            "analysis": f"DeepSeek API 调用失败: {e}",
            "basket": "TOO_HARD",
            "score": _calc_score(fin),
            "source": "api_error",
        }


# ── 缓存（含版本号，代码升级自动失效） ─────────────────────────────────────

CACHE_VERSION = "v2.3"  # 改代码时递增此版本，旧缓存自动失效

def _cache_get(stock_code: str) -> dict | None:
    rows = execute_query(
        "SELECT analysis_json FROM munger_cache WHERE stock_code=%s AND cache_version=%s",
        (stock_code, CACHE_VERSION),
    )
    return json.loads(rows[0]["analysis_json"]) if rows else None


def _cache_set(stock_code: str, result: dict) -> None:
    execute_update(
        "INSERT INTO munger_cache (stock_code, analysis_json, cache_version) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE analysis_json=VALUES(analysis_json)",
        (stock_code, json.dumps(result, ensure_ascii=False), CACHE_VERSION),
    )


# ── 主入口 ───────────────────────────────────────────────────────────────────

def analyze(stock_code: str, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = _cache_get(stock_code)
        if cached:
            cached["cached"] = True
            return cached

    fin = _gather_financials(stock_code)
    if not fin["rows"]:
        return {"analysis": "没有足够财务数据。", "basket": "TOO_HARD",
                "score": 0, "cached": False}

    ai = _call_deepseek(fin)

    result = {
        "analysis": ai.get("analysis", ""),
        "basket": ai.get("basket", "TOO_HARD"),
        "score": ai.get("score", _calc_score(fin)),
        "source": ai.get("source", "local"),
        "cached": False,
    }
    if result["source"] == "deepseek":
        _cache_set(stock_code, result)
    return result
