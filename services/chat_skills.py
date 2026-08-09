"""Skill and DeepSeek model registry for the stock research chat.

The registry deliberately contains product contracts rather than provider code.
This keeps the chat orchestrator stable while new analysis skills are added.
"""

from __future__ import annotations

import json
from typing import Any

from config_manager import get_config, get_deepseek_model


SKILL_SPECS: dict[str, dict[str, Any]] = {
    "munger": {
        "label": "芒格思维",
        "version": "munger-v3",
        "description": "逆向思考、护城河、激励结构和永久性亏损分析",
        "requires": ["business", "financial", "market", "risk"],
        "topics": (),
        "source_policy": "none",
        "system_prompt": "munger",
        "default_model": "deepseek-v4-pro",
    },
    "stock_analyst": {
        "label": "标准股票分析",
        "version": "stock-analyst-v1",
        "description": "具体业务、商业模式、财务数据和业绩预估",
        "requires": ["business", "financial", "market", "industry", "forecast"],
        "topics": ("最新财务与公告", "行业与竞争", "估值与市场"),
        "source_policy": "disclosure_first",
        "system_prompt": "stock_analyst",
        "default_model": "deepseek-v4-pro",
    },
    "valuation": {
        "label": "估值分析",
        "version": "valuation-v1",
        "description": "估值方法、假设、情景和估值失效条件",
        "requires": ["financial", "market", "forecast", "industry"],
        "topics": ("估值与市场", "最新财务与公告"),
        "source_policy": "mixed",
        "system_prompt": "valuation",
        "default_model": "deepseek-v4-pro",
    },
    "financial_report": {
        "label": "财报解读",
        "version": "financial-report-v1",
        "description": "报告期、利润质量、现金流、资产负债表和重大事项",
        "requires": ["financial", "business"],
        "topics": ("最新财务与公告",),
        "source_policy": "disclosure_first",
        "system_prompt": "financial_report",
        "default_model": "deepseek-chat",
    },
    "industry_research": {
        "label": "行业研究",
        "version": "industry-research-v1",
        "description": "行业规模、供需、竞争、政策和公司行业位置",
        "requires": ["business", "financial", "industry"],
        "topics": ("行业与竞争", "最新财务与公告"),
        "source_policy": "mixed",
        "system_prompt": "industry_research",
        "default_model": "deepseek-v4-pro",
    },
    "portfolio": {
        "label": "投资组合",
        "version": "portfolio-v1",
        "description": "持仓集中度、行业暴露、收益来源和压力测试",
        "requires": ["portfolio", "market", "risk"],
        "topics": (),
        "source_policy": "none",
        "system_prompt": "portfolio",
        "default_model": "deepseek-chat",
    },
    "risk_review": {
        "label": "风险排查",
        "version": "risk-review-v1",
        "description": "业务、财务、行业、治理和永久性亏损风险",
        "requires": ["business", "financial", "industry", "market", "risk"],
        "topics": ("风险与负面", "最新财务与公告", "行业与竞争"),
        "source_policy": "disclosure_first",
        "system_prompt": "risk_review",
        "default_model": "deepseek-v4-pro",
    },
}


COMPOSITE_SKILLS = {
    "auto": {"label": "自动选择", "version": "router-v1", "description": "根据问题选择一个主 Skill 和最多一个辅助 Skill"},
}


DEFAULT_MODELS = [
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "purpose": "复杂研究和长篇分析",
        "enabled": True,
        "supports_stream": True,
        "max_tokens": 2400,
        "temperature": 0.3,
    },
    {
        "id": "deepseek-chat",
        "label": "DeepSeek Chat",
        "purpose": "快速问答和财报摘要",
        "enabled": True,
        "supports_stream": True,
        "max_tokens": 1600,
        "temperature": 0.3,
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek Reasoner",
        "purpose": "估值、风险和复杂推理",
        "enabled": True,
        "supports_stream": True,
        "max_tokens": 2600,
        "temperature": 0.2,
    },
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "purpose": "低延迟股票问答和快速迭代",
        "enabled": True,
        "supports_stream": True,
        "max_tokens": 1800,
        "temperature": 0.3,
    },
]


def canonical_model_id(model_id: str | None) -> str | None:
    """Normalize display/user aliases to the provider model ID."""
    if model_id is None:
        return None
    value = str(model_id).strip().lower()
    compact = value.replace("-", "").replace("_", "").replace(" ", "")
    if compact == "deepseekv4flash":
        return "deepseek-v4-flash"
    return value


def get_skill_specs() -> list[dict[str, Any]]:
    result = []
    for skill_id, spec in SKILL_SPECS.items():
        result.append({"id": skill_id, **{key: value for key, value in spec.items() if key not in {"system_prompt"}}})
    result.extend({"id": skill_id, **spec} for skill_id, spec in COMPOSITE_SKILLS.items())
    return result


def get_model_specs() -> list[dict[str, Any]]:
    raw = get_config("deepseek_models", "")
    models = list(DEFAULT_MODELS)
    if raw:
        try:
            configured = json.loads(raw)
            if isinstance(configured, list):
                configured_models = [
                    item for item in configured
                    if isinstance(item, dict) and item.get("id")
                ]
                if configured_models:
                    models = configured_models
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    normalised = []
    for model in models:
        item = dict(model)
        item["id"] = canonical_model_id(item.get("id"))
        item.setdefault("label", item.get("id"))
        item.setdefault("purpose", "DeepSeek 股票研究模型")
        item["enabled"] = bool(item.get("enabled", True))
        item["supports_stream"] = bool(item.get("supports_stream", True))
        try:
            item["max_tokens"] = max(256, int(item.get("max_tokens", 1600)))
        except (TypeError, ValueError):
            item["max_tokens"] = 1600
        try:
            item["temperature"] = float(item.get("temperature", 0.3))
        except (TypeError, ValueError):
            item["temperature"] = 0.3
        normalised.append(item)
    return normalised


def get_model_spec(model_id: str | None = None) -> dict[str, Any]:
    requested = canonical_model_id(model_id or get_deepseek_model())
    models = get_model_specs()
    for model in models:
        if model.get("id") == requested and model.get("enabled", True):
            return model
    for model in models:
        if model.get("id") == canonical_model_id(get_deepseek_model()) and model.get("enabled", True):
            return model
    return models[0] if models else dict(DEFAULT_MODELS[0])


def resolve_skill_id(skill_id: str | None) -> str:
    if skill_id in SKILL_SPECS or skill_id in COMPOSITE_SKILLS:
        return skill_id
    return "munger"


def resolve_model_id(model_id: str | None, skill_id: str) -> str:
    if model_id:
        return get_model_spec(canonical_model_id(model_id)).get("id")
    return get_model_spec(SKILL_SPECS.get(skill_id, {}).get("default_model")).get("id")


def skill_spec(skill_id: str | None) -> dict[str, Any]:
    resolved = resolve_skill_id(skill_id)
    if resolved in SKILL_SPECS:
        return SKILL_SPECS[resolved]
    return COMPOSITE_SKILLS.get(resolved, SKILL_SPECS["munger"])


def skill_search_plan(skill_id: str | None, intent: str, default_topics=(), default_policy="mixed") -> tuple[tuple[str, ...], str]:
    if intent == "framework" and not default_topics:
        return (), "none"
    spec = skill_spec(skill_id)
    topics = spec.get("topics") or default_topics
    policy = spec.get("source_policy") or default_policy
    if skill_id == "munger" or not skill_id:
        return tuple(default_topics), default_policy
    return tuple(topics), policy


def choose_skill_for_question(message: str) -> tuple[str, str | None]:
    """Return (primary skill, optional helper skill) for automatic mode."""
    text = (message or "").lower()
    if any(word in text for word in ("持仓", "组合", "仓位", "再平衡", "集中度")):
        return "portfolio", "risk_review"
    if any(word in text for word in ("行业", "供需", "竞争格局", "市场空间", "政策", "同行")):
        return "industry_research", "risk_review"
    if any(word in text for word in ("贵不贵", "估值", "pe", "pb", "合理价", "目标价", "买入价")):
        return "valuation", "financial_report"
    if any(word in text for word in ("财报", "年报", "季报", "现金流", "应收账款", "存货", "利润质量")):
        return "financial_report", None
    if any(word in text for word in ("风险", "亏损", "诉讼", "监管", "减值", "债务")):
        return "risk_review", "financial_report"
    if any(word in text for word in ("护城河", "芒格", "逆向", "永久性亏损", "能力圈", "管理层激励")):
        return "munger", "risk_review"
    return "stock_analyst", None


SYSTEM_PROMPTS = {
    "stock_analyst": "你是严谨的公司研究分析师，重点分析具体业务、商业模式、财务数据和可验证的业绩驱动。不要冒充芒格本人。",
    "valuation": "你是保守的股票估值分析师，必须明确估值方法、数据日期、假设、情景和失效条件，不得编造精确目标价。",
    "financial_report": "你是财报解读分析师，只根据报告期数据、正式披露和给定上下文回答，严格区分历史事实、公司指引和你的推断。",
    "industry_research": "你是行业研究分析师，重点分析规模、供需、竞争、政策、上下游和公司行业位置，财经媒体只能作为补充。",
    "portfolio": "你是投资组合分析师，只使用真实持仓、权重、行情和交易数据，重点分析集中度、暴露、压力测试和缺失的投资者约束。",
    "risk_review": "你是保守的风险排查分析师，输出风险登记表、触发条件、影响指标和跟踪信号，不把可能性写成已经发生的事实。",
}


OUTPUT_GUIDANCE = {
    "stock_analyst": "建议结构：### 一句话结论\n### 公司业务\n### 商业模式\n### 财务数据\n### 业绩预估\n### 主要风险",
    "valuation": "建议结构：### 估值结论\n### 当前估值数据\n### 估值方法和关键假设\n### 悲观/基准/乐观情景\n### 估值失效条件",
    "financial_report": "建议结构：### 财报摘要\n### 本期业绩变化\n### 收入和利润质量\n### 现金流\n### 资产负债表\n### 重大事项",
    "industry_research": "建议结构：### 行业结论\n### 行业规模和增速\n### 供需关系\n### 竞争格局\n### 政策和监管\n### 公司行业位置",
    "portfolio": "建议结构：### 组合结论\n### 持仓集中度\n### 行业和风格暴露\n### 收益来源\n### 压力测试\n### 需要补充的数据",
    "risk_review": "建议结构：### 风险总评\n### 高优先级风险\n### 风险触发条件和影响\n### 风险监控清单\n### 最坏情景",
}


def system_prompt(skill_id: str) -> str | None:
    return SYSTEM_PROMPTS.get(skill_id)


def output_guidance(skill_id: str) -> str:
    return OUTPUT_GUIDANCE.get(skill_id, "")
