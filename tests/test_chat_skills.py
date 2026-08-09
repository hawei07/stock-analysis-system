import unittest
from unittest.mock import patch

import munger
from services import chat_skills
from services.stock_analysis_context import build_skill_context


class ChatSkillRegistryTests(unittest.TestCase):
    def test_registry_contains_requested_skills(self):
        ids = {item["id"] for item in chat_skills.get_skill_specs()}
        self.assertTrue({
            "munger",
            "stock_analyst",
            "valuation",
            "financial_report",
            "industry_research",
            "portfolio",
            "risk_review",
            "auto",
        }.issubset(ids))

    def test_model_registry_has_whitelist_and_reasoner(self):
        ids = {item["id"] for item in chat_skills.get_model_specs()}
        self.assertIn("deepseek-chat", ids)
        self.assertIn("deepseek-reasoner", ids)
        self.assertIn("deepseek-v4-flash", ids)
        self.assertEqual(chat_skills.canonical_model_id("DeepSeekV4FLASH"), "deepseek-v4-flash")
        self.assertEqual(chat_skills.get_model_spec("DeepSeekV4FLASH")["id"], "deepseek-v4-flash")
        self.assertIn(chat_skills.get_model_spec("not-allowed")["id"], ids)
        self.assertNotEqual(chat_skills.get_model_spec("not-allowed")["id"], "not-allowed")

    def test_auto_router_selects_specialised_skill(self):
        self.assertEqual(chat_skills.choose_skill_for_question("这家公司 PE 贵不贵？")[0], "valuation")
        self.assertEqual(chat_skills.choose_skill_for_question("我的组合集中度如何？")[0], "portfolio")


class SharedSkillContextTests(unittest.TestCase):
    def test_valuation_context_contains_selected_forecast(self):
        financial = {
            "annual_rows": [
                {"fiscal_year": 2023, "report_period": "FY", "total_revenue": 100, "parent_profit": 10},
                {"fiscal_year": 2024, "report_period": "FY", "total_revenue": 120, "parent_profit": 12},
                {"fiscal_year": 2025, "report_period": "FY", "total_revenue": 150, "parent_profit": 18},
            ],
            "info": {"industry": "测试行业"},
            "warnings": [],
        }

        context = build_skill_context(
            lambda *_args, **_kwargs: [],
            "600000",
            financial,
            "valuation",
            forecast_horizon=5,
            forecast_scenario="bear",
        )

        self.assertEqual(context["forecast"]["selected_scenario"], "bear")
        self.assertEqual(context["forecast"]["horizon"], 5)
        self.assertIn("industry", context)

    def test_portfolio_without_positions_reports_missing_data(self):
        context = build_skill_context(
            lambda *_args, **_kwargs: [],
            "600000",
            {"info": {}, "warnings": []},
            "portfolio",
        )
        self.assertFalse(context["portfolio"]["available"])
        self.assertTrue(context["portfolio"]["warnings"])


class ChatSkillIntegrationTests(unittest.TestCase):
    def test_load_base_uses_selected_skill_and_model(self):
        fin = {
            "info": {"code": "600000", "name": "测试股票", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "rows": [],
            "market": {},
            "warnings": [],
        }
        model_spec = {
            "id": "deepseek-reasoner",
            "label": "Reasoner",
            "enabled": True,
            "max_tokens": 2600,
            "temperature": 0.2,
        }
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "get_deepseek_model", return_value="deepseek-chat"), \
                patch.object(munger, "get_model_specs", return_value=chat_skills.DEFAULT_MODELS), \
                patch.object(munger, "get_model_spec", return_value=model_spec), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "_load_chat_history_text", return_value=""), \
                patch.object(munger, "get_chat_memory", return_value=None), \
                patch.object(munger, "build_skill_context", return_value={}), \
                patch.object(munger, "format_skill_context", return_value=""):
            base = munger._load_chat_base(
                "600000",
                "估值是否合理？",
                skill_id="valuation",
                model_id="deepseek-reasoner",
                forecast_horizon=5,
                forecast_scenario="bull",
            )

        self.assertEqual(base["skill_id"], "valuation")
        self.assertEqual(base["model"], "deepseek-reasoner")
        self.assertEqual(base["forecast_horizon"], 5)
        self.assertEqual(base["forecast_scenario"], "bull")
        self.assertEqual(munger._chat_system_message(base).startswith("你是保守的股票估值分析师"), True)

    def test_sse_done_contains_skill_and_model_metadata(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "rows": [],
            "market": {"quote_time": "2026-08-09 15:00"},
            "warnings": [],
        }

        class Delta:
            content = "### 事实\n无\n### 推断\n无\n### 判断\n谨慎\n### 缺失数据\n无"

        class Client:
            def __init__(self):
                self.chat = type("Chat", (), {
                    "completions": type("Completions", (), {
                        "create": lambda *_args, **_kwargs: [type("Chunk", (), {
                            "choices": [type("Choice", (), {"delta": Delta()})()]
                        })()]
                    })()
                })()

        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "get_deepseek_model", return_value="deepseek-chat"), \
                patch.object(munger, "get_model_specs", return_value=chat_skills.DEFAULT_MODELS), \
                patch.object(munger, "get_model_spec", return_value=chat_skills.DEFAULT_MODELS[2]), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "OpenAI", return_value=Client()), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "execute_update", return_value=1):
            events = list(munger.chat_stream(
                "600000",
                "估值是否合理？",
                skill_id="valuation",
                model_id="deepseek-reasoner",
            ))

        done = events[-1]["data"]
        self.assertEqual(done["meta"]["skill_id"], "valuation")
        self.assertEqual(done["meta"]["model_id"], "deepseek-reasoner")
        self.assertEqual(done["meta"]["forecast_scenario"], "base")


if __name__ == "__main__":
    unittest.main()
