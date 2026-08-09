import unittest
from unittest.mock import patch

import munger


class _Delta:
    def __init__(self, content, reasoning_content=""):
        self.content = content
        self.reasoning_content = reasoning_content


class _Chunk:
    def __init__(self, content, reasoning_content="", finish_reason=None):
        self.choices = [type(
            "Choice",
            (),
            {"delta": _Delta(content, reasoning_content), "finish_reason": finish_reason},
        )()]


class _StreamingCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return [_Chunk("### 事实\n数据"), _Chunk("\n### 推断\n推断"), _Chunk("\n### 判断\n判断\n### 缺失数据\n无")]


class _StreamingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _StreamingCompletions()})()


class _EmptyThenNonStreamingCompletions:
    def __init__(self, fallback_content):
        self.calls = []
        self.fallback_content = fallback_content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return [_Chunk("", reasoning_content="内部推理", finish_reason="length")]
        message = type("Message", (), {"content": self.fallback_content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class _EmptyThenNonStreamingClient:
    def __init__(self, fallback_content):
        completions = _EmptyThenNonStreamingCompletions(fallback_content)
        self.chat = type("Chat", (), {"completions": completions})()


class _FlashEmptyThenProCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["model"] == "deepseek-v4-pro":
            return [_Chunk("### 事实\n备用模型已返回")]
        if kwargs.get("stream"):
            return [_Chunk("", reasoning_content="内部推理", finish_reason="length")]
        message = type("Message", (), {"content": ""})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class _FlashEmptyThenProClient:
    def __init__(self):
        completions = _FlashEmptyThenProCompletions()
        self.chat = type("Chat", (), {"completions": completions})()


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

    def test_sse_retries_non_stream_when_flash_only_returns_reasoning(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "market": {},
            "warnings": [],
        }
        client = _EmptyThenNonStreamingClient(
            "### 事实\n数据\n### 推断\n推断\n### 判断\n谨慎\n### 缺失数据\n无"
        )
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "get_deepseek_model", return_value="deepseek-v4-flash"), \
                patch.object(munger, "get_model_specs", return_value=munger.get_model_specs()), \
                patch.object(munger, "get_model_spec", return_value={
                    "id": "deepseek-v4-flash",
                    "label": "DeepSeek V4 Flash",
                    "enabled": True,
                    "max_tokens": 1800,
                    "temperature": 0.3,
                }), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "OpenAI", return_value=client), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "execute_update", return_value=1):
            events = list(munger.chat_stream(
                "600000",
                "全面分析这家公司",
                skill_id="stock_analyst",
                model_id="deepseek-v4-flash",
            ))

        self.assertEqual(events[-1]["event"], "done")
        self.assertIn("### 事实", events[-1]["data"]["reply"])
        calls = client.chat.completions.calls
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0]["stream"])
        self.assertNotIn("stream", calls[1])
        self.assertEqual(calls[1]["max_tokens"], 3200)

    def test_sse_error_names_selected_skill_when_retry_is_empty(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "market": {},
            "warnings": [],
        }
        client = _EmptyThenNonStreamingClient("")
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "get_deepseek_model", return_value="deepseek-v4-flash"), \
                patch.object(munger, "get_model_specs", return_value=munger.get_model_specs()), \
                patch.object(munger, "get_model_spec", return_value={
                    "id": "deepseek-v4-flash",
                    "label": "DeepSeek V4 Flash",
                    "enabled": True,
                    "max_tokens": 1800,
                    "temperature": 0.3,
                }), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "OpenAI", return_value=client), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "execute_update", return_value=1):
            events = list(munger.chat_stream(
                "600000",
                "全面分析这家公司",
                skill_id="stock_analyst",
                model_id="deepseek-v4-flash",
            ))

        self.assertEqual(events[-1]["event"], "error")
        self.assertEqual(events[-1]["data"]["error"], "标准股票分析暂时不可用，请稍后重试。")

    def test_sse_falls_back_to_enabled_model_and_records_actual_model(self):
        fin = {
            "info": {"name": "测试股票", "code": "600000", "industry": "测试行业"},
            "period_note": "2026 一季报",
            "latest_period": None,
            "latest_annual": None,
            "yoy_base": None,
            "market": {},
            "warnings": [],
        }
        client = _FlashEmptyThenProClient()
        with patch.object(munger, "get_deepseek_api_key", return_value="test-key"), \
                patch.object(munger, "_gather_financials", return_value=fin), \
                patch.object(munger, "get_deepseek_model", return_value="deepseek-v4-flash"), \
                patch.object(munger, "get_model_specs", return_value=munger.get_model_specs()), \
                patch.object(munger, "get_model_spec", return_value={
                    "id": "deepseek-v4-flash",
                    "label": "DeepSeek V4 Flash",
                    "enabled": True,
                    "max_tokens": 1800,
                    "temperature": 0.3,
                }), \
                patch.object(munger, "_collect_chat_sources", return_value=("", [], False, [])), \
                patch.object(munger, "_build_chat_prompt", return_value="prompt"), \
                patch.object(munger, "OpenAI", return_value=client), \
                patch.object(munger, "execute_query", return_value=[]), \
                patch.object(munger, "execute_update", return_value=1):
            events = list(munger.chat_stream(
                "600000",
                "全面分析这家公司",
                skill_id="stock_analyst",
                model_id="deepseek-v4-flash",
            ))

        self.assertEqual(events[-1]["event"], "done")
        done = events[-1]["data"]
        self.assertEqual(done["model_id"], "deepseek-v4-pro")
        self.assertEqual(done["meta"]["requested_model_id"], "deepseek-v4-flash")
        self.assertTrue(any("DeepSeek V4 Pro" in warning for warning in done["meta"]["warnings"]))
        self.assertTrue(any(
            event["event"] == "phase" and event["data"].get("stage") == "model_fallback"
            for event in events
        ))

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
