"""Run a small, repeatable evaluation set for Munger chat prompts/models.

Examples:
  python evals/run_munger_eval.py --limit 3 --output evals/results/v3.json
  python evals/run_munger_eval.py --model deepseek-chat --prompt-version v4 \
      --system-prompt-file prompts/munger-v4.txt --with-search \
      --output evals/results/v4-deepseek-chat.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI

import munger
from config_manager import get_deepseek_api_key, get_deepseek_model


def load_questions(path: Path, limit: int | None = None):
    items = json.loads(path.read_text(encoding="utf-8"))
    return items[:limit] if limit else items


def object_value(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def model_reply(client, model, system_prompt, user_prompt):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=1600,
    )
    choices = object_value(response, "choices", []) or []
    message = object_value(choices[0], "message", {}) if choices else {}
    return (object_value(message, "content", "") or "").strip()


def score_item(item, reply, sources, elapsed_ms):
    reply = reply or ""
    required = item.get("required_sections") or []
    missing_sections = [section for section in required if f"### {section}" not in reply]
    source_ids = {source.get("id") for source in sources if source.get("id")}
    cited_ids = set(re.findall(r"\[([A-Za-z0-9_-]*-S\d+|S\d+)\]", reply))
    invalid_citations = sorted(cited_ids - source_ids - {f"S{i}" for i in range(1, 20)})
    official_source = any(source.get("source_tier") in {1, 2} for source in sources)
    target_price_pattern = re.compile(r"(?:目标价|合理股价|买入价)\s*[:：]?\s*\d+(?:\.\d+)?")
    invented_target_price = bool(target_price_pattern.search(reply))
    checks = {
        "intent_sections_present": not missing_sections,
        "citations_valid": not invalid_citations,
        "has_sources_when_required": bool(sources) if item.get("must_have_sources") else True,
        "official_source_present": official_source if item.get("must_have_sources") else True,
        "no_invented_target_price": not (item.get("must_not_invent_target_price") and invented_target_price),
        "has_uncertainty_language": any(word in reply for word in ("缺失", "不能判断", "需核验", "数据不足", "Too Hard")),
    }
    passed = sum(bool(value) for value in checks.values())
    return {
        "checks": checks,
        "score": round(passed / max(len(checks), 1) * 100, 2),
        "missing_sections": missing_sections,
        "cited_ids": sorted(cited_ids),
        "invalid_citations": invalid_citations,
        "invented_target_price": invented_target_price,
        "official_source_present": official_source,
        "output_chars": len(reply),
        "elapsed_ms": round(elapsed_ms, 2),
    }


def build_context(question, with_search):
    base = munger._load_chat_base(question["stock_code"], question["question"])
    if with_search:
        return munger._complete_chat_context(base)
    base.update({
        "research_text": "",
        "sources": [],
        "search_used": False,
        "search_warnings": [],
        "source_collected_at": None,
    })
    base["prompt"] = munger._build_chat_prompt(
        base["fin"], base["history_text"], "", base["message"], base["route"]["intent"], base["memory_text"]
    )
    base["meta"] = munger._chat_meta(
        base["fin"], [], False, [], base["model"], base["route"]["intent"], base["turn_id"], base["route"]["source_policy"]
    )
    return base


def main():
    parser = argparse.ArgumentParser(description="Evaluate Munger chat prompt/model variants")
    parser.add_argument("--questions", type=Path, default=ROOT / "evals" / "munger_chat_questions.json")
    parser.add_argument("--model", default=None, help="DeepSeek model override")
    parser.add_argument("--system-prompt-file", type=Path, default=None)
    parser.add_argument("--prompt-version", default=munger.CHAT_PROMPT_VERSION)
    parser.add_argument("--with-search", action="store_true", help="Fetch the configured evidence sources")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    key = get_deepseek_api_key()
    if not key:
        parser.error("DeepSeek API Key 未配置")
    model = args.model or get_deepseek_model()
    system_prompt = (
        args.system_prompt_file.read_text(encoding="utf-8")
        if args.system_prompt_file else munger.CHAT_SYSTEM
    )
    questions = load_questions(args.questions, args.limit)
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=60, max_retries=1)
    results = []
    for item in questions:
        started = time.perf_counter()
        try:
            context = build_context(item, args.with_search)
            reply = model_reply(client, model, system_prompt, context["prompt"])
            metrics = score_item(item, reply, context["sources"], (time.perf_counter() - started) * 1000)
            result = {
                "id": item["id"],
                "stock_code": item["stock_code"],
                "expected_intent": item.get("expected_intent"),
                "actual_intent": context["route"]["intent"],
                "model": model,
                "prompt_version": args.prompt_version,
                "with_search": args.with_search,
                "reply": reply,
                "sources": context["sources"],
                **metrics,
            }
        except Exception as exc:
            result = {
                "id": item["id"],
                "stock_code": item["stock_code"],
                "model": model,
                "prompt_version": args.prompt_version,
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        results.append(result)
        print(f"{item['id']}: {result.get('score', 0)} ({result.get('elapsed_ms', 0)} ms)")

    scored = [item for item in results if "score" in item]
    summary = {
        "model": model,
        "prompt_version": args.prompt_version,
        "question_count": len(results),
        "scored_count": len(scored),
        "average_score": round(sum(item["score"] for item in scored) / len(scored), 2) if scored else 0,
        "average_elapsed_ms": round(sum(item.get("elapsed_ms", 0) for item in results) / max(len(results), 1), 2),
        "intent_accuracy": round(sum(item.get("actual_intent") == item.get("expected_intent") for item in scored) / len(scored) * 100, 2) if scored else 0,
        "results": results,
    }
    output = args.output
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"saved: {output}")
    else:
        print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
