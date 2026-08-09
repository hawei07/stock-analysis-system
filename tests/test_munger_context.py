import unittest
from datetime import datetime
from unittest.mock import patch

import munger
from services.financial_periods import filter_usable_report_rows
from services.munger_context import build_financial_context


def _financial_row(year, period, *, revenue=100, profit=20, cashflow=30, roe=15):
    return {
        "fiscal_year": year,
        "report_period": period,
        "total_revenue": revenue,
        "operate_profit": 999,
        "parent_profit": profit,
        "operate_cashflow": cashflow,
        "roe": roe,
        "roic": 10,
        "debt_ratio": 40,
        "basic_eps": 1.2,
        "inc_operating_revenue": revenue,
        "inc_cost_of_revenue": 40,
        "inc_selling_expense": 10,
        "inc_admin_expense": 5,
        "inc_finance_expense": 2,
        "inc_rd_expense": 0,
        "inc_tax_surcharge": 1,
        "inc_interest_expense": 0,
        "inc_fee_commission_expense": 0,
        "inc_finance_interest_income": 0,
    }


class MungerContextTests(unittest.TestCase):
    def test_chat_intent_changes_with_question_type(self):
        self.assertEqual(munger._classify_chat_intent("什么是护城河？"), "framework")
        self.assertEqual(
            munger._classify_chat_intent("如何理解这家公司当前的护城河？"),
            "industry",
        )
        self.assertEqual(
            munger._classify_chat_intent("这只股票最新 ROE 是多少？"),
            "fact",
        )
        self.assertEqual(
            munger._classify_chat_intent("这只股票最新业绩怎么样？"),
            "financial",
        )
        self.assertEqual(
            munger._classify_chat_intent("这只股票现在贵不贵？"),
            "valuation",
        )
        self.assertEqual(
            munger._classify_chat_intent("这家公司怎么会亏钱？"),
            "risk",
        )
        self.assertEqual(
            munger._classify_chat_intent("全面分析这家公司"),
            "comprehensive",
        )
        self.assertEqual(
            munger._classify_chat_intent("请核验 https://example.com/report"),
            "link",
        )

    def test_stock_specific_framework_question_still_searches(self):
        topics = munger._search_topics_for_message("如何理解这只股票的护城河？", [])
        self.assertIn("行业与竞争", topics)

    def test_prompt_contains_dynamic_output_guidance(self):
        current_year = datetime.now().year
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": f"{current_year} 一季报",
            "latest_period": _financial_row(current_year, "Q1"),
            "yoy_base": _financial_row(current_year - 1, "Q1"),
            "latest_annual": _financial_row(current_year - 1, "FY"),
            "rows": [],
            "market": {},
            "warnings": [],
        }
        prompt = munger._build_chat_prompt(
            fin,
            "",
            "",
            "这只股票现在贵不贵？",
            "valuation",
        )
        self.assertIn("本轮回答模式", prompt)
        self.assertIn("估值判断（valuation）", prompt)
        self.assertIn("### 估值结论", prompt)
        self.assertNotIn("### 护城河与激励", prompt)

    def test_context_uses_current_quarter_and_same_period_last_year(self):
        current_year = datetime.now().year
        rows = [
            _financial_row(current_year - 1, "FY", revenue=90, profit=18),
            _financial_row(current_year - 1, "Q1", revenue=40, profit=8),
            _financial_row(current_year, "Q1", revenue=50, profit=10),
            # 只有季度数据时，部分数据源会把当前季报错误标为 FY。
            _financial_row(current_year, "FY", revenue=50, profit=10),
        ]

        def fake_query(sql, params=None):
            if "FROM stocks" in sql:
                return [{
                    "code": "600025",
                    "name": "华能水电",
                    "market": "SH",
                    "industry": "电力",
                    "list_date": None,
                    "status": "正常",
                    "pe_ttm": 18,
                    "dividend_yield": 2,
                }]
            if "FROM custom_financials" in sql:
                return rows
            if "graham_valuations" in sql:
                return []
            raise AssertionError(sql)

        with patch("services.munger_context._load_market_context", return_value={}), \
                patch("services.munger_context._load_graham_context", return_value={}):
            context = build_financial_context(fake_query, "600025")

        self.assertEqual(context["period_note"], f"{current_year} 一季报")
        self.assertEqual(context["yoy_note"], f"{current_year} 一季报 vs {current_year - 1} 一季报")
        self.assertEqual(context["latest_annual"]["fiscal_year"], current_year - 1)
        self.assertTrue(any("疑似误标" in warning for warning in context["warnings"]))
        # 核心利润来自统一的利润表明细口径，而不是 custom_financials 中的旧摘要值 999。
        self.assertAlmostEqual(context["latest_period"]["operate_profit"], -8)
        self.assertAlmostEqual(context["latest_period"]["core_profit_rate"], -16)

    def test_suspicious_fy_can_be_excluded_without_fallback(self):
        current_year = datetime.now().year
        rows = [{"fiscal_year": current_year, "report_period": "FY"}]
        self.assertEqual(
            filter_usable_report_rows(rows, current_year=current_year, allow_fallback=False),
            [],
        )
        self.assertEqual(
            filter_usable_report_rows(rows, current_year=current_year),
            rows,
        )

    def test_framework_question_does_not_search_but_stock_question_does(self):
        self.assertEqual(munger._search_topics_for_message("什么是护城河？", []), [])
        self.assertIn("最新财务与公告", munger._search_topics_for_message("这只股票最新业绩怎么样？", []))

    def test_source_reliability_parses_url_without_match_indexing(self):
        self.assertEqual(munger._source_reliability("https://www.cninfo.com.cn/a"), "披露/交易所来源")
        self.assertEqual(munger._source_reliability("not-a-url"), "公开网页，未核验")

    def test_prompt_contains_stock_identity_and_period_aware_revenue(self):
        current_year = datetime.now().year
        fin = {
            "info": {"name": "华能水电", "code": "600025", "market": "SH", "industry": "电力"},
            "period_note": f"{current_year} 一季报",
            "latest_period": _financial_row(current_year, "Q1", revenue=50, profit=10),
            "yoy_base": _financial_row(current_year - 1, "Q1", revenue=40, profit=8),
            "latest_annual": _financial_row(current_year - 1, "FY", revenue=90, profit=18),
            "rows": [_financial_row(current_year - 1, "FY", revenue=90, profit=18)],
            "market": {},
            "warnings": [],
        }
        prompt = munger._build_chat_prompt(fin, "", "", "这只股票怎么样？")
        self.assertIn("华能水电", prompt)
        self.assertIn("600025", prompt)
        self.assertIn("同周期营收同比", prompt)
        self.assertIn("50", prompt)
        self.assertIn(f"最新完整年报：{current_year - 1} 年报", prompt)

    def test_model_failure_returns_http_error_without_fake_assistant_reply(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": None,
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "market": {},
            "warnings": [],
        }
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "get_deepseek_model", return_value="test-model"), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "OpenAI", side_effect=RuntimeError("provider unavailable")), \
                patch.object(munger, "execute_update") as update:
            result = munger.chat_send("600000", "这只股票怎么样？")

        self.assertEqual(result["_http_status"], 502)
        self.assertIn("暂时不可用", result["error"])
        self.assertNotIn("reply", result)
        update.assert_not_called()

    def test_success_persists_user_and_assistant_metadata(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": _financial_row(2026, "Q1"),
            "latest_annual": _financial_row(2025, "FY"),
            "yoy_base": _financial_row(2025, "Q1"),
            "market": {},
            "warnings": [],
        }

        class FakeResponse:
            choices = [type("Choice", (), {
                "message": type("Message", (), {"content": "### 结论\n数据充分。"})()
            })()]

        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return FakeResponse()

        class FakeClient:
            def __init__(self):
                self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        updates = []

        def record_update(sql, params=None):
            updates.append((sql, params))
            return 1

        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "get_deepseek_model", return_value="test-model"), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "OpenAI", return_value=FakeClient()), \
                patch.object(munger, "execute_update", side_effect=record_update):
            result = munger.chat_send("600000", "请分析这只股票")

        self.assertEqual(result["reply"], "### 结论\n数据充分。")
        self.assertEqual(result["meta"]["latest_period"], "2026 一季报")
        self.assertEqual(len(updates), 2)
        self.assertIn("meta_json", updates[1][0])


if __name__ == "__main__":
    unittest.main()
