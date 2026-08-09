# 对话芒格股票问题评测集

`munger_chat_questions.json` 是一组可重复运行的股票问题样本，覆盖框架、事实、财务表现、估值、风险、管理层、行业、链接核验、综合分析和数据缺失场景。每条样本都定义了预期意图、必须出现的信息区块、是否要求来源，以及禁止编造目标价等约束。

## 运行

先确保系统设置中已经配置 DeepSeek API Key，然后在项目根目录执行：

```powershell
python evals/run_munger_eval.py --limit 3 --output evals/results/chat-v3.json
```

比较不同模型：

```powershell
python evals/run_munger_eval.py --model deepseek-v4-pro --prompt-version v3 --output evals/results/v3-v4-pro.json
python evals/run_munger_eval.py --model deepseek-chat --prompt-version v3 --output evals/results/v3-chat.json
```

也可以在一次运行中比较多个模型，并切换到任意已注册 Skill：

```powershell
python evals/run_munger_eval.py --skill valuation --models deepseek-chat,deepseek-reasoner --prompt-version v4 --output evals/results/valuation-models.json
python evals/run_munger_eval.py --skill financial_report --models deepseek-chat,deepseek-v4-pro --output evals/results/financial-report-models.json
```

支持的 Skill 包括 `munger`、`stock_analyst`、`valuation`、`financial_report`、`industry_research`、`portfolio`、`risk_review` 和 `auto`。默认模型包括 `deepseek-chat`、`deepseek-reasoner`、`deepseek-v4-pro` 和 `deepseek-v4-flash`。模型列表来自后端白名单；如果在 `system_config.deepseek_models` 中配置 JSON，评测脚本和网页下拉框会共同使用这份配置。

比较不同 Prompt：

```powershell
python evals/run_munger_eval.py --system-prompt-file prompts/munger-v4.txt --prompt-version v4 --output evals/results/v4.json
```

默认不联网搜索，适合先比较 Prompt 和模型本身；加 `--with-search` 后会按问题意图抓取正式披露和补充资料：

```powershell
python evals/run_munger_eval.py --with-search --output evals/results/v3-with-search.json
```

## 评分

脚本会保存每道题的回答、意图、来源、耗时和检查结果，并汇总：

- 必须的“事实 / 推断 / 判断 / 缺失数据”区块是否齐全；
- 引用 ID 是否有效；
- 要求来源时是否真的有来源，且是否包含正式披露/监管来源；
- 是否出现没有依据的目标价、合理股价或买入价；
- 是否明确表达数据缺失、不能判断或需要核验；
- 意图路由准确率、平均得分和平均耗时。

这是一套回归评测，不是投资建议。模型升级、Prompt 变更或来源策略调整后，应固定问题集和运行参数，再比较结果文件。
