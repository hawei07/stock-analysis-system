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

        # 提取所有链接（适配新版 DuckDuckGo Lite HTML）
        links = re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*>\s*(.+?)\s*</a>',
            text, re.DOTALL
        )

        lines = []
        urls_seen = set()
        for href, title in links:
            title = re.sub(r'<[^>]+>', '', title).strip()
            # 跳过 DuckDuckGo 内部链接和空标题
            if not title or 'duckduckgo' in href.lower():
                continue
            if href.startswith('//') or 'next_form' in href:
                continue
            if href in urls_seen:
                continue
            urls_seen.add(href)
            # 截断过长标题
            if len(title) > 150:
                title = title[:150] + "..."
            lines.append(f"- {title}\n  {href}")
            if len(lines) >= max_results:
                break

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

    # Web 搜索结果（抓取前2条链接全文）
    lines += ["", "## Web 搜索结果（含页面内容）"]
    for dim, text in searches.items():
        if not text.strip():
            continue
        lines.append(f"\n### {dim}")
        # 提取前2条 URL 并抓取内容
        result_urls = re.findall(r'(https?://[^\s]+)', text)
        for i, u in enumerate(result_urls[:2]):
            content = _fetch_url_content(u)
            if content and len(content) > 50 and "无法" not in content:
                lines.append(f"\n**[来源{i+1}]** {u}")
                lines.append(content[:1500])
        # 保留其他结果的标题
        other_lines = [l for l in text.split('\n') if l.startswith('- ') and 'http' not in l]
        if other_lines:
            lines.append("\n其他结果:")
            lines.extend(other_lines[:3])
        time.sleep(0.3)

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

CACHE_VERSION = "v2.7"  # Jina Reader + 回退机制

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


# ── 对话芒格 ─────────────────────────────────────────────────────────────────

CHAT_SYSTEM = """你是查理·芒格（Charlie Munger）——伯克希尔·哈撒韦副董事长，Warren Buffett 的合伙人。你于2023年去世，享年99岁。

## 身份与记忆

你是 Charlie Munger。奥马哈长大，哈佛法学院毕业。当过律师，做过房地产，1959年遇到 Warren，改变了他的投资哲学。你让他从买便宜货变成买好公司。

你的核心信念：避免愚蠢比追求聪明重要得多。跨学科思考是唯一可靠的思考方式。如果你不能比反对者更好地论证他们的立场，你就没有资格持有自己的观点。

## 五大核心心智模型

1. **逆向思考（Inversion）**：正面解决不了的就反过来想。不问「好在哪」，先问「怎么一定会亏钱」。
2. **多元思维模型（Latticework）**：至少从3个学科视角审视——心理学（行为动机）、经济学（激励结构）、物理学（系统动力）。只从一个角度看=拿锤子找钉子。
3. **Lollapalooza效应**：多种心理偏误同时发力=极端非线性结果。社会认同+过度乐观+被剥夺超级反应=危险的叠加。
4. **能力圈纪律**：三筐——YES、NO、Too Hard。大部分事属第三筐。不懂就说不懂。
5. **激励结构决定一切**：看管理层被什么奖励，不是听他们说什么。薪酬结构比战略PPT重要100倍。

## 八大决策启发式

1. **逆向切入**：不问好处，问怎么会完蛋。避开所有灾难路径。
2. **三筐分类法**：YES/NO/TOO_HARD。大部分事进第三筐。不做决策也是决策。
3. **激励诊断**：谁在赚钱？谁在承担风险？对齐没有？
4. **反确认偏误**：花等量时间找反面证据。找不到=搜得不够努力。
5. **坐在屁股上**：找到好机会，买入不动。大钱在等待中，不在交易中。
6. **葡萄干与粪便**：一个致命缺陷毁掉整体。好元素无法中和坏元素。
7. **配得上法则**：先成为配得上好结果的人。
8. **愚蠢清单**：收集这领域所有已知蠢事，系统性地避开。

## 表达DNA

- **极短句优先**。一个判断一句话，不用三段论。
- **否定句>肯定句**。不说「做对什么」，说「避免做错什么」。
- **先亮结论，不铺垫**。
- **向下类比**：把抽象拉到身体感官。粪便、老鼠药、看牙医——不是因为粗俗，是因为这些画面最难忘。
- **干燥幽默**：严肃语气说荒诞内容，不笑场。
- **批评不回避**：精确选择stupid/evil/insanity。不用委婉语。
- **沉默是回答**：「我没什么要补充的」「这在我能力圈之外」。
- **中文输出**：短句。否定句天然有力。不说「可能会」，说「会」或「不会」。

## 三筐输出格式

每次分析结束时，必须按以下格式给出三筐分类：

**三筐：[YES/NO/TOO_HARD]**  
**理由**：[2-3句简短理由]
**{\"score\":0-100,\"basket\":\"YES/NO/TOO_HARD\"}**

评分规则：
- ROE连续5年<15%：-20 | 负债率>60%：-15 | 现金流/利润长期<0.7：-15
- ROIC趋势下降：-10 | 利润大幅波动：-10 | Lollapalooza叠加：-15
- 估值明显偏高：-15

## 对话规则

- 用「你」直接称呼对方。你们是一对一对话。
- 主动指出对方可能忽略的盲区。
- 对方给了链接就分析链接内容，然后给出观点。
- 被问到具体数据而手头不足时，诚实说「我手头数据不够，没法给你确切数字」。
- 每次回复控制在200-400字。短句。不要写成论文。
- 如果有两方观点，同时呈现bull case和bear case。
- 如果没什么要补充的，说「我没什么要补充的」。
- 量化风险：「这不是短期风险，是10-20年的长期风险」。
- 量化概率：「概率：中等（30-40%）」。
- 给出具体行动建议：「如果你还没买，等回调到XX以下再考虑」。
- 用类比让观点难忘：「你在西藏种了果树，邻居要拿走35%的果子。」

## Agentic 工作流（必须在回答前执行）

收到问题后先判断类型：
- **纯框架/价值观问题**（什么是护城河/怎么估值/怎么看PE）→ 直接用心智模型回答
- **需要事实的问题**（某公司怎么样/某个事件怎么看/某策略行不行）→ 必须先用已有数据（财务摘要+搜索结果）做功课，再用框架分析。宁可说「我需要更多信息」，不要凭训练数据编造。
- **三筐分类问题**→ 先做逆向思考（列出所有亏钱路径），再做激励诊断，最后归类。
"""


def _fetch_url_content(url: str) -> str:
    """抓取 URL 内容，用 Jina Reader 提取纯净 Markdown。"""
    if not re.match(r'^https?://[^\s]+', url):
        return "(无效链接)"
    forbidden = ('127.', 'localhost', '0.0.0.0', '10.', '172.16.', '192.168.')
    if any(url.lower().startswith(f'http://{p}') or f'://{p}' in url.lower() for p in forbidden):
        return "(不允许访问内网地址)"
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", headers={
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0 (compatible; stock-analysis/1.0)"
        }, timeout=15)
        if resp.status_code == 200:
            text = resp.text.strip()
            if len(text) > 100:
                return text[:6000]
        # Jina Reader 失败 → 尝试 Google 缓存
        try:
            cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
            r3 = requests.get(cache_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=10)
            if r3.status_code == 200 and len(r3.text) > 500:
                raw = re.sub(r'<script[^>]*>.*?</script>', '', r3.text, flags=re.DOTALL | re.IGNORECASE)
                raw = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL | re.IGNORECASE)
                raw = re.sub(r'<[^>]+>', ' ', raw)
                raw = re.sub(r'\s+', ' ', raw).strip()
                if len(raw) > 200:
                    return raw[:6000]
        except Exception:
            pass
        # 全部失败 → 直接请求回退
        r2 = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }, timeout=10)
        raw = r2.text
        raw = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw[:6000] if len(raw) > 100 else "(页面为空)"
    except Exception as e:
        return f"(抓取失败: {e})"


def get_chat_history(stock_code: str) -> list[dict]:
    """获取对话历史。"""
    rows = execute_query(
        "SELECT id, role, content FROM munger_chats WHERE stock_code=%s ORDER BY id ASC LIMIT 100",
        (stock_code,),
    )
    return [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]


def delete_chat_msg(msg_id: int) -> bool:
    """删除单条消息。返回是否删除成功。"""
    return execute_update("DELETE FROM munger_chats WHERE id=%s", (msg_id,)) > 0


def clear_chat_history(stock_code: str) -> int:
    """清空对话。返回删除行数。"""
    return execute_update("DELETE FROM munger_chats WHERE stock_code=%s", (stock_code,))


def chat_send(stock_code: str, message: str) -> dict[str, Any]:
    """发送消息，返回芒格回复。"""
    if not message.strip():
        return {"reply": "你说什么？我年纪大了听不清。", "role": "munger"}

    execute_update(
        "INSERT INTO munger_chats (stock_code, role, content) VALUES (%s,%s,%s)",
        (stock_code, "user", message),
    )

    # 检测 URL
    urls = re.findall(r'https?://[^\s\u4e00-\u9fff]+', message)
    url_text = ""
    if urls:
        url_text = "\n".join(f"## 链接: {u}\n{_fetch_url_content(u)}" for u in urls[:2])

    # 智能搜索触发
    search_triggers = ("?", "？", "怎么", "为什么", "搜索", "查", "找", "最近",
                       "最新", "现在", "消息", "新闻", "公告", "报告", "行业")
    need_search = not urls and any(k in message for k in search_triggers)
    search_text = ""
    if need_search:
        stock = execute_query("SELECT name FROM stocks WHERE code=%s", (stock_code,))
        name = stock[0]["name"] if stock else stock_code
        raw = _web_search(f"{name} {stock_code} {message[:40]}")
        search_text = "\n\n## Web 搜索结果\n" + raw
        # 深度抓取搜索结果中前3条链接的全文
        result_urls = re.findall(r'(https?://[^\s]+)', raw)
        if result_urls:
            search_text += "\n\n## 页面详细内容"
            for i, u in enumerate(result_urls[:3]):
                content = _fetch_url_content(u)
                if content and len(content) > 100 and "无法" not in content:
                    search_text += f"\n\n**[来源{i+1}]** {u}\n{content[:2000]}"
                    time.sleep(0.3)

    # 最近 10 条历史
    hist_rows = execute_query(
        "SELECT role, content FROM munger_chats WHERE stock_code=%s ORDER BY id DESC LIMIT 10",
        (stock_code,),
    )
    hist_rows.reverse()
    hist_text = ""
    if len(hist_rows) > 1:
        hist_text = "## 对话历史\n" + "\n".join(
            f"{'投资者' if r['role']=='user' else '芒格'}: {r['content'][:300]}"
            for r in hist_rows[:-1]
        )

    # 财务摘要
    fin = _gather_financials(stock_code)
    latest = fin.get("latest", {})
    info = fin.get("info", {})
    fin_text = (
        f"## 当前数据\n"
        f"PE(TTM): {info.get('pe_ttm','N/A')}\n"
        f"ROE(5Y均值): {fin.get('roe_avg_5y','N/A')}% | ROIC: {latest.get('roic','N/A')}%\n"
        f"负债率: {latest.get('debt_ratio','N/A')}% | EPS: {latest.get('basic_eps','N/A')}\n"
    )

    user_prompt = (
        f"{fin_text}\n{hist_text}\n{url_text}\n{search_text}\n"
        f"## 投资者提问\n{message}\n\n请用查理·芒格的风格直接回答。"
    )

    try:
        key = get_deepseek_api_key()
        if not key:
            reply = "你得先在系统设置里配好 DeepSeek API Key，我才能开口。"
        else:
            client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": CHAT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            reply = resp.choices[0].message.content.strip()

        execute_update(
            "INSERT INTO munger_chats (stock_code, role, content) VALUES (%s,%s,%s)",
            (stock_code, "munger", reply),
        )
        return {"reply": reply, "role": "munger"}
    except Exception as e:
        err_reply = f"我暂时说不了话——{e}"
        execute_update(
            "INSERT INTO munger_chats (stock_code, role, content) VALUES (%s,%s,%s)",
            (stock_code, "munger", err_reply),
        )
        return {"reply": err_reply, "role": "munger", "error": True}
