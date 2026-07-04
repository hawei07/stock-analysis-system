"""芒格视角分析模块 — 财务数据打包 + Web搜索 + DeepSeek分析 + 缓存评分。

流程:
  1. 从 DB 拉取 10 年财务数据
  2. Web 搜索最新公开信息
  3. 打包 System Prompt（芒格 Skill） + User Prompt（数据 + 搜索结果）
  4. 调用 DeepSeek V4 API
  5. 计算芒格评分 (0-100)
  6. 写入 munger_cache 并返回
"""

import json
import re
import hashlib
import time
from typing import Any

import requests
from openai import OpenAI

from db import execute_query, execute_update
from config_manager import get_deepseek_api_key

# ── 芒格 System Prompt（基于 munger-perspective Skill 提炼） ─────────────────

MUNGER_SYSTEM = """你是查理·芒格（Charlie Munger）——伯克希尔·哈撒韦副董事长，Warren Buffett 的合伙人。

## 你的思维框架

1. **逆向思考**：不问「这股票好在哪」，先问「什么情况下投它一定亏钱」
2. **多元思维模型**：从心理学、经济学、物理学多角度审视，不只盯着财报
3. **Lollapalooza 效应**：多种偏误同时发力时最危险
4. **能力圈纪律**：不懂的就说不懂，放进 Too Hard 筐
5. **激励结构决定一切**：看管理层被什么奖励，不是听他们说什么
6. **配得上法则**：好公司要配得上它的估值
7. **坐在屁股上**：找到好公司后，最好的策略是持有不动
8. **葡萄干与粪便**：一个好指标救不了一堆坏指标

## 分析输出格式

输出 JSON（不要 markdown 代码块包裹，直接纯 JSON）：

{
  "verdict": "一句话定性，芒格风格，极短句，不用铺垫",
  "analysis": "详细分析，100-200字，指出最关键的 2-3 个信号（正面或负面），用逆向思考点出最大的风险",
  "basket": "YES / NO / TOO_HARD",
  "score": 0-100 的整数
}

## 评分规则

- 满分 100，每条扣分原因扣 5-20 分
- ROE 连续 5 年 < 15%：-20 分
- 资产负债率 > 60%：-15 分
- 经营现金流/净利润长期 < 0.7：-15 分
- ROIC 趋势下降：-10 分
- 近 3 年利润大幅波动：-10 分
- 你识别到任何 Lollapalooza 风险叠加：-15 分
- 估值明显偏高（无需精确，合理判断）：-15 分

## 表达风格

- 极短句优先，否定句 > 肯定句
- 不讲委婉话，直接说「蠢」/「危险」/「还行」
- 干燥幽默，但不要为了幽默而幽默
- 说中文，用短句
"""

# ── Web 搜索 ─────────────────────────────────────────────────────────────────

def _web_search(query: str, max_results: int = 3) -> str:
    """用 DuckDuckGo Lite 搜索，返回文本摘要。"""
    try:
        url = "https://lite.duckduckgo.com/lite/"
        resp = requests.post(url, data={"q": query}, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=10)
        # 简单提取链接标题和摘要
        results = re.findall(
            r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>.*?<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            resp.text, re.DOTALL | re.IGNORECASE
        )
        if not results:
            # fallback: just grab titles
            results = re.findall(r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>', resp.text)
            results = [(t, "") for t in results]

        lines = []
        for i, (title, snippet) in enumerate(results[:max_results]):
            title = re.sub(r'<[^>]+>', '', title).strip()
            snippet = re.sub(r'<[^>]+>', '', snippet).strip()
            lines.append(f"- {title}" + (f": {snippet}" if snippet else ""))
        return "\n".join(lines) if lines else "(无搜索结果)"
    except Exception as e:
        return f"(搜索失败: {e})"


# ── 财务数据打包 ─────────────────────────────────────────────────────────────

def _gather_financials(stock_code: str) -> dict[str, Any]:
    """拉取近 10 年 FY 财务数据，返回结构化字典。"""
    rows = execute_query("""
        SELECT cf.fiscal_year, cf.total_revenue, cf.operate_profit,
               cf.parent_profit, cf.deducted_profit, cf.operate_cashflow,
               cf.roe, cf.roic, cf.debt_ratio, cf.basic_eps,
               cf.total_assets, cf.total_equity
        FROM custom_financials cf
        WHERE cf.stock_code = %s AND cf.report_period = 'FY'
        ORDER BY cf.fiscal_year DESC
        LIMIT 10
    """, (stock_code,))

    stock = execute_query(
        "SELECT code, name, industry, list_date FROM stocks WHERE code = %s", (stock_code,)
    )
    info = stock[0] if stock else {}

    # 计算关键指标
    roe_list = []
    profit_list = []
    cf_ratio_list = []
    for r in rows:
        pp = float(r["parent_profit"]) if r["parent_profit"] else 0
        oc = float(r["operate_cashflow"]) if r["operate_cashflow"] else 0
        roe_list.append(float(r["roe"]) if r["roe"] else 0)
        profit_list.append(pp)
        cf_ratio_list.append(oc / pp if pp != 0 else None)

    roe_avg = sum(roe_list[:5]) / min(5, len(roe_list)) if roe_list else 0
    roe_trend = "上升" if len(roe_list) >= 3 and roe_list[0] > roe_list[-1] else \
                "下降" if len(roe_list) >= 3 and roe_list[0] < roe_list[-1] else "平稳"
    cf_quality = sum(1 for v in cf_ratio_list if v and v > 0.7) / max(1, sum(1 for v in cf_ratio_list if v is not None))

    return {
        "info": info,
        "years_count": len(rows),
        "roe_avg_5y": round(roe_avg, 1),
        "roe_trend": roe_trend,
        "cf_quality_ratio": round(cf_quality, 2),
        "latest": rows[0] if rows else {},
        "rows": [dict(r) for r in rows],
    }


# ── 评分逻辑 ─────────────────────────────────────────────────────────────────

def _calc_score(fin: dict) -> int:
    """基于财务数据计算芒格评分（0-100）。"""
    score = 100
    reasons = []

    roe5 = fin["roe_avg_5y"]
    if roe5 < 10:
        score -= 20; reasons.append("ROE过低")
    elif roe5 < 15:
        score -= 10; reasons.append("ROE偏低")

    latest = fin["latest"]
    dr = float(latest.get("debt_ratio") or 0)
    if dr > 70:
        score -= 15; reasons.append("负债率过高")
    elif dr > 50:
        score -= 7; reasons.append("负债率偏高")

    if fin["cf_quality_ratio"] < 0.5:
        score -= 15; reasons.append("现金流质量差")
    elif fin["cf_quality_ratio"] < 0.7:
        score -= 7; reasons.append("现金流偏弱")

    if fin["roe_trend"] == "下降":
        score -= 10; reasons.append("ROE趋势下降")

    # 利润波动检查
    profits = [float(r["parent_profit"] or 0) for r in fin["rows"][:5]]
    if profits and max(profits) > 0 and min(profits) > 0:
        volatility = (max(profits) - min(profits)) / max(profits)
        if volatility > 0.5:
            score -= 10; reasons.append("利润大幅波动")

    return max(0, min(100, score))


# ── DeepSeek 分析 ────────────────────────────────────────────────────────────

def _build_user_prompt(fin: dict, news: str) -> str:
    """构建发送给 DeepSeek 的 User Prompt。"""
    info = fin["info"]
    latest = fin["latest"]

    lines = [
        f"## 股票: {info.get('name','')} ({info.get('code','')})",
        f"行业: {info.get('industry','未知')} | 上市: {info.get('list_date','')}",
        "",
        "## 近 10 年关键财务数据",
        f"ROE（近 5 年均值）: {fin['roe_avg_5y']}%，趋势: {fin['roe_trend']}",
        f"ROIC（最新）: {latest.get('roic','N/A')}%",
        f"资产负债率（最新）: {latest.get('debt_ratio','N/A')}%",
        f"经营现金流/净利润达标率: {fin['cf_quality_ratio']:.0%}",
        f"最新营收: {latest.get('total_revenue','N/A')}亿",
        f"最新归母净利润: {latest.get('parent_profit','N/A')}亿",
        f"最新 EPS: {latest.get('basic_eps','N/A')}",
        "",
        "## 年度明细",
        "| 年份 | 营收(亿) | 营业利润 | 净利润 | ROE% | ROIC% | 负债率% | 现金流/利润 |",
        "|------|---------|---------|--------|------|-------|---------|------------|",
    ]

    for r in fin["rows"][:10]:
        pp = float(r.get("parent_profit") or 0)
        oc = float(r.get("operate_cashflow") or 0)
        cf_r = f"{oc/pp:.1f}" if pp != 0 else "-"
        lines.append(
            f"| {r['fiscal_year']} | {r.get('total_revenue','-')} | "
            f"{r.get('operate_profit','-')} | {r.get('parent_profit','-')} | "
            f"{r.get('roe','-')} | {r.get('roic','-')} | "
            f"{r.get('debt_ratio','-')} | {cf_r} |"
        )

    # 逆向搜索：强制搜索负面信息
    stock_name = info.get("name", "")
    stock_code = info.get("code", "")

    lines += [
        "",
        "## 最新公开信息",
        f"【正面/中性】{news['general']}",
        f"【风险/负面】{news['risks']}",
        "",
        "请用查理·芒格的视角，基于以上数据，给出你的分析。输出纯 JSON。",
    ]
    return "\n".join(lines)


def _call_deepseek(fin: dict) -> dict[str, Any]:
    """调用 DeepSeek API 获取芒格分析。"""
    api_key = get_deepseek_api_key()
    if not api_key:
        return {"verdict": "请先在系统设置中配置 DeepSeek API Key",
                "analysis": "", "basket": "TOO_HARD", "score": 0, "source": "no_key"}

    # Web 搜索
    stock_name = fin["info"].get("name", "")
    stock_code = fin["info"].get("code", "")
    news = {
        "general": _web_search(f"{stock_name} {stock_code} 最新财报 业绩"),
        "risks": _web_search(f"{stock_name} {stock_code} 风险 负面 争议"),
    }

    user_prompt = _build_user_prompt(fin, news)

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": MUNGER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        text = resp.choices[0].message.content.strip()
        # 清理可能的 markdown 代码块包裹
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        result["source"] = "deepseek"
        return result
    except json.JSONDecodeError:
        return {"verdict": "AI 分析解析失败", "analysis": text[:300],
                "basket": "TOO_HARD", "score": 0, "source": "parse_error"}
    except Exception as e:
        return {"verdict": f"API 调用失败", "analysis": str(e)[:200],
                "basket": "TOO_HARD", "score": 0, "source": "api_error"}


# ── 缓存 ─────────────────────────────────────────────────────────────────────

def _cache_key(stock_code: str) -> str:
    rows = execute_query(
        "SELECT MAX(fiscal_year) y FROM custom_financials WHERE stock_code=%s",
        (stock_code,)
    )
    r = rows[0] if rows else {}
    raw = f"{stock_code}|{r.get('y','')}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(stock_code: str) -> dict | None:
    rows = execute_query(
        "SELECT analysis_json FROM munger_cache WHERE stock_code=%s",
        (stock_code,),
    )
    return json.loads(rows[0]["analysis_json"]) if rows else None


def _cache_set(stock_code: str, result: dict) -> None:
    execute_update(
        "INSERT INTO munger_cache (stock_code, analysis_json) VALUES (%s,%s) "
        "ON DUPLICATE KEY UPDATE analysis_json=VALUES(analysis_json)",
        (stock_code, json.dumps(result, ensure_ascii=False)),
    )


# ── 主入口 ───────────────────────────────────────────────────────────────────

def analyze(stock_code: str, force_refresh: bool = False) -> dict[str, Any]:
    """芒格视角分析一只股票，返回 {verdict, analysis, basket, score, ...}"""
    ch = _cache_key(stock_code)

    if not force_refresh:
        cached = _cache_get(stock_code)
        if cached:
            cached["cached"] = True
            return cached

    fin = _gather_financials(stock_code)

    if not fin["rows"]:
        return {"verdict": "没有足够财务数据", "analysis": "",
                "basket": "TOO_HARD", "score": 0, "cached": False}

    # AI 分析
    ai = _call_deepseek(fin)

    # 补充本地评分
    if ai.get("source") != "deepseek":
        ai["score"] = _calc_score(fin)

    result = {
        "verdict": ai.get("verdict", ""),
        "analysis": ai.get("analysis", ""),
        "basket": ai.get("basket", "TOO_HARD"),
        "score": ai.get("score", _calc_score(fin)),
        "source": ai.get("source", "local"),
        "cached": False,
    }

    # 写入缓存
    _cache_set(stock_code, result)
    return result
