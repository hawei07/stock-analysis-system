"""Shared non-prompt context for the multi-skill stock research chat."""

from __future__ import annotations

from typing import Any

from services.financial_metrics import pct_change


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _load_segments(execute_query, stock_code: str) -> list[dict[str, Any]]:
    try:
        rows = execute_query(
            """SELECT fiscal_year, report_period, dimension_type, segment_name, revenue,
                      cost, gross_profit, gross_margin, revenue_ratio, profit_ratio, source
               FROM business_segments WHERE stock_code=%s AND report_period='FY'
               ORDER BY fiscal_year DESC, revenue DESC""",
            (stock_code,),
        )
    except Exception:
        return []
    result = []
    for row in rows:
        item = dict(row)
        for key in ("revenue", "cost", "gross_profit", "gross_margin", "revenue_ratio", "profit_ratio"):
            item[key] = _number(item.get(key))
        result.append(item)
    return result


def _build_forecast(
    fin: dict[str, Any],
    horizon: int = 3,
    scenario_name: str = "base",
) -> dict[str, Any]:
    annual = fin.get("annual_rows") or fin.get("rows") or []
    annual = sorted(annual, key=lambda row: (int(row.get("fiscal_year") or 0), str(row.get("report_period") or "")))
    if not annual:
        return {"available": False, "warnings": ["没有足够的完整年报数据，无法建立基础业绩预估"]}

    recent = annual[-3:]
    revenues = [_number(row.get("total_revenue")) for row in recent]
    profits = [_number(row.get("parent_profit")) for row in recent]
    revenue_growth = []
    profit_growth = []
    for previous, current in zip(recent, recent[1:]):
        revenue_growth.append(pct_change(current.get("total_revenue"), previous.get("total_revenue")))
        profit_growth.append(pct_change(current.get("parent_profit"), previous.get("parent_profit")))

    latest = recent[-1]
    revenue_rates = [value for value in revenue_growth if value is not None]
    profit_rates = [value for value in profit_growth if value is not None]
    revenue_rate = round(sum(revenue_rates) / len(revenue_rates), 2) if revenue_rates else None
    profit_rate = round(sum(profit_rates) / len(profit_rates), 2) if profit_rates else None

    def scenario(rate, multiplier):
        return round(rate * multiplier, 2) if rate is not None else None

    try:
        horizon = min(max(int(horizon), 1), 10)
    except (TypeError, ValueError):
        horizon = 3
    scenario_name = scenario_name if scenario_name in {"bear", "base", "bull"} else "base"
    selected = {
        "bear": {"revenue_growth": scenario(revenue_rate, 0.5), "profit_growth": scenario(profit_rate, 0.35)},
        "base": {"revenue_growth": revenue_rate, "profit_growth": profit_rate},
        "bull": {"revenue_growth": scenario(revenue_rate, 1.35), "profit_growth": scenario(profit_rate, 1.5)},
    }[scenario_name]

    def compound(value, growth):
        if value is None or growth is None:
            return None
        try:
            return round(value * (1 + growth / 100) ** horizon, 2)
        except (TypeError, ValueError, OverflowError):
            return None

    return {
        "available": True,
        "base_year": latest.get("fiscal_year"),
        "base_period": latest.get("report_period"),
        "base_revenue": latest.get("total_revenue"),
        "base_profit": latest.get("parent_profit"),
        "historical_revenue_growth": revenue_growth,
        "historical_profit_growth": profit_growth,
        "average_revenue_growth": revenue_rate,
        "average_profit_growth": profit_rate,
        "scenarios": {
            "bear": {"revenue_growth": scenario(revenue_rate, 0.5), "profit_growth": scenario(profit_rate, 0.35)},
            "base": {"revenue_growth": revenue_rate, "profit_growth": profit_rate},
            "bull": {"revenue_growth": scenario(revenue_rate, 1.35), "profit_growth": scenario(profit_rate, 1.5)},
        },
        "selected_scenario": scenario_name,
        "horizon": horizon,
        "projection": {
            "revenue": compound(_number(latest.get("total_revenue")), selected.get("revenue_growth")),
            "profit": compound(_number(latest.get("parent_profit")), selected.get("profit_growth")),
        },
        "warnings": ["这是基于历史趋势的情景估算，不是公司正式业绩指引"] if revenue_rate is not None else ["历史增长数据不足"],
    }


def _load_portfolio(execute_query, stock_code: str | None = None) -> dict[str, Any]:
    sql = """SELECT p.stock_code, p.shares, p.cost_price, s.name, s.market, s.industry
             FROM portfolio_positions p LEFT JOIN stocks s ON s.code=p.stock_code"""
    params = ()
    if stock_code:
        sql += " WHERE p.stock_code=%s"
        params = (stock_code,)
    try:
        rows = execute_query(sql, params)
    except Exception:
        # Older installations may have created portfolio_positions before the
        # cost basis column was added. Keep the skill useful and mark cost data
        # as missing instead of failing the whole chat request.
        try:
            fallback = sql.replace("p.cost_price", "NULL AS cost_price")
            rows = execute_query(fallback, params)
        except Exception:
            return {"available": False, "positions": [], "warnings": ["组合数据不可用"]}
    positions = []
    for row in rows:
        item = dict(row)
        item["shares"] = _number(item.get("shares"))
        item["cost_price"] = _number(item.get("cost_price"))
        positions.append(item)
    total_cost = sum((item.get("shares") or 0) * (item.get("cost_price") or 0) for item in positions)
    by_industry: dict[str, float] = {}
    for item in positions:
        industry = item.get("industry") or "未分类"
        by_industry[industry] = by_industry.get(industry, 0) + (item.get("shares") or 0) * (item.get("cost_price") or 0)
    return {
        "available": bool(positions),
        "positions": positions,
        "total_cost": round(total_cost, 2),
        "industry_allocations": [
            {"industry": key, "cost_value": round(value, 2), "allocation_pct": round(value / total_cost * 100, 2) if total_cost else None}
            for key, value in sorted(by_industry.items(), key=lambda item: item[1], reverse=True)
        ],
        "warnings": [] if positions else ["当前没有持仓数据，无法完成组合分析"],
    }


def build_skill_context(
    execute_query,
    stock_code: str,
    financial: dict[str, Any],
    skill_id: str,
    *,
    forecast_horizon: int = 3,
    forecast_scenario: str = "base",
) -> dict[str, Any]:
    """Build only the extra contexts requested by a skill."""
    requires = set((financial.get("skill_requires") or []))
    context: dict[str, Any] = {}
    if "business" in requires or skill_id in {"stock_analyst", "industry_research", "risk_review", "munger"}:
        segments = _load_segments(execute_query, stock_code)
        context["business"] = {
            "segments": segments,
            "latest_segment_year": max((item.get("fiscal_year") or 0 for item in segments), default=None),
            "segment_warnings": [] if segments else ["没有可用的业务板块拆分数据"],
        }
    if "financial" in requires or skill_id in {
        "stock_analyst", "financial_report", "valuation", "risk_review", "munger"
    }:
        context["financial"] = {
            "latest_period": financial.get("latest_period"),
            "latest_annual": financial.get("latest_annual"),
            "roe_avg_5y": financial.get("roe_avg_5y"),
            "roe_trend": financial.get("roe_trend"),
            "cashflow_quality": financial.get("cf_quality"),
            "profit_cagr": financial.get("cagr"),
            "warnings": list(financial.get("warnings") or []),
        }
    if "forecast" in requires or skill_id in {"stock_analyst", "valuation"}:
        context["forecast"] = _build_forecast(
            financial,
            horizon=forecast_horizon,
            scenario_name=forecast_scenario,
        )
    if "portfolio" in requires or skill_id == "portfolio":
        context["portfolio"] = _load_portfolio(execute_query)
    if "industry" in requires or skill_id in {"industry_research", "risk_review", "valuation"}:
        context["industry"] = {
            "name": (financial.get("info") or {}).get("industry"),
            "peer_data": [],
            "warnings": ["同行和行业公开数据需要通过本轮正式资料补充"],
        }
    if "risk" in requires or skill_id in {"risk_review", "portfolio", "munger"}:
        context["risk"] = {
            "warnings": list(financial.get("warnings") or []),
            "monitoring": ["报告期是否更新", "经营现金流是否持续弱于利润", "负债率和减值风险是否上升"],
        }
    return context


def format_skill_context(context: dict[str, Any]) -> str:
    """Serialize shared context into a compact, clearly labelled prompt section."""
    lines = []
    business = context.get("business") or {}
    segments = business.get("segments") or []
    if segments:
        lines.extend(["## 业务板块数据（正式数据优先）"])
        for item in segments[:20]:
            lines.append(
                f"- {item.get('fiscal_year')} {item.get('dimension_type')} {item.get('segment_name')}: "
                f"收入 {item.get('revenue')} 亿元，毛利 {item.get('gross_profit')} 亿元，毛利率 {item.get('gross_margin')}%"
            )
    elif business:
        lines.extend(["## 业务板块数据", "- 缺失"])

    forecast = context.get("forecast") or {}
    if forecast:
        lines.extend(["", "## 基础业绩情景估算（不是公司指引）"])
        lines.append(f"- 基准年度：{forecast.get('base_year')}，历史平均收入增速：{forecast.get('average_revenue_growth')}%")
        lines.append(f"- 历史平均归母净利润增速：{forecast.get('average_profit_growth')}%")
        for name, scenario in (forecast.get("scenarios") or {}).items():
            lines.append(f"- {name}：收入增速 {scenario.get('revenue_growth')}%，利润增速 {scenario.get('profit_growth')}%")
        projection = forecast.get("projection") or {}
        lines.append(
            f"- 当前选择：{forecast.get('selected_scenario')} 情景，{forecast.get('horizon')} 年后收入粗略值 {projection.get('revenue')}，利润粗略值 {projection.get('profit')}"
        )
        lines.extend(f"- 提示：{warning}" for warning in forecast.get("warnings") or [])

    financial = context.get("financial") or {}
    if financial:
        lines.extend(["", "## 财报质量摘要（本地计算）"])
        lines.append(
            f"- 近五年 ROE 均值：{financial.get('roe_avg_5y')}%，趋势：{financial.get('roe_trend') or '缺失'}；"
            f"经营现金流质量：{financial.get('cashflow_quality')}%；利润 CAGR：{financial.get('profit_cagr')}%"
        )
        lines.extend(f"- 提示：{warning}" for warning in financial.get("warnings") or [])

    portfolio = context.get("portfolio") or {}
    if portfolio:
        lines.extend(["", "## 投资组合数据（只代表当前记录）"])
        lines.append(f"- 持仓数量：{len(portfolio.get('positions') or [])}，成本金额：{portfolio.get('total_cost')}")
        for item in (portfolio.get("industry_allocations") or [])[:10]:
            lines.append(f"- 行业 {item.get('industry')}：成本占比 {item.get('allocation_pct')}%")
        lines.extend(f"- 提示：{warning}" for warning in portfolio.get("warnings") or [])

    industry = context.get("industry") or {}
    if industry:
        lines.extend(["", "## 行业上下文"])
        lines.append(f"- 公司行业：{industry.get('name') or '缺失'}")
        lines.extend(f"- 提示：{warning}" for warning in industry.get("warnings") or [])

    risk = context.get("risk") or {}
    if risk:
        lines.extend(["", "## 风险监控提示（不是已经发生的事实）"])
        lines.extend(f"- {item}" for item in risk.get("monitoring") or [])
        lines.extend(f"- 数据提示：{warning}" for warning in risk.get("warnings") or [])

    return "\n".join(lines)
