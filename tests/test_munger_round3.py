import unittest
from unittest.mock import patch

import munger


class _Delta:
    def __init__(self, content):
        self.content = content


class _Chunk:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"delta": _Delta(content)})()]


class _StreamingCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return [_Chunk("### 事实\n数据"), _Chunk("\n### 推断\n推断"), _Chunk("\n### 判断\n判断\n### 缺失数据\n无")]


class _StreamingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _StreamingCompletions()})()


class MungerRound3Tests(unittest.TestCase):
    def test_sse_stream_emits_phases_deltas_and_done(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "market": {"quote_time": "2026-08-09 15:00"},
            "warnings": [],
        }
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "get_deepseek_model", return_value="test-model"), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "OpenAI", return_value=_StreamingClient()), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "execute_update", return_value=1):
            events = list(munger.chat_stream("600000", "分析最新业绩"))

        names = [event["event"] for event in events]
        self.assertIn("phase", names)
        self.assertIn("delta", names)
        self.assertEqual(names[-1], "done")
        done = events[-1]["data"]
        self.assertEqual(done["turn_id"].startswith("T"), True)
        self.assertEqual(done["meta"]["quote_time"], "2026-08-09 15:00")
        self.assertEqual(done["meta"]["prompt_version"], munger.CHAT_PROMPT_VERSION)

    def test_delete_turn_is_scoped_to_stock_and_turn(self):
        with patch.object(munger, "execute_update", return_value=2) as update:
            self.assertEqual(munger.delete_chat_turn("600000", "Tabc123"), 2)
        sql, params = update.call_args.args
        self.assertIn("stock_code=%s", sql)
        self.assertIn("turn_id=%s", sql)
        self.assertEqual(params, ("600000", "Tabc123"))

    def test_memory_is_explicitly_marked_as_non_factual_context(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "rows": [],
            "market": {},
            "warnings": [],
        }
        prompt = munger._build_chat_prompt(fin, "", "", "怎么看", "comprehensive", "关注现金流")
        self.assertIn("长期对话摘要", prompt)
        self.assertIn("不是当前财务事实", prompt)
        self.assertIn("关注现金流", prompt)


if __name__ == "__main__":
    unittest.main()
