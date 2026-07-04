# Agency Agents Router — Hermes 安装备忘

## 安装步骤

```bash
git clone https://github.com/msitarzewski/agency-agents.git
cd agency-agents
python scripts/build-hermes-plugin.py --repo-root . --out integrations/hermes
mkdir -p ~/AppData/Local/hermes/plugins
cp -R integrations/hermes/agency-agents-router ~/AppData/Local/hermes/plugins/
```

## Windows 注意事项

1. **`python3` 不存在**：convert.sh 和 install.sh 使用 `python3`，Windows 上只有 `python`。必须手动运行 `build-hermes-plugin.py` 和手动复制插件。

2. **Hermes config 路径不一致**：
   - install.sh 假设：`~/.hermes/config.yaml`
   - Windows 实际：`~/AppData/Local/hermes/config.yaml`
   - 插件应安装到：`~/AppData/Local/hermes/plugins/`

3. **启用插件需手动编辑 config.yaml**，在末尾添加：
   ```yaml
   plugins:
     enabled:
       - agency-agents-router
   ```

4. **安装后必须重启 Hermes** 才能加载新工具。

## 使用的工具

安装后 Hermes 获得 4 个新工具（toolset: `agency_agents`）：

| 工具 | 作用 |
|------|------|
| `agency_agents_search` | 按关键词/部门搜索 233 个专家 |
| `agency_agents_inspect` | 查看专家元数据或完整 Prompt |
| `agency_agents_load` | 加载专家 Prompt 到当前会话 |
| `agency_agents_delegate` | 委派任务给专家（后台执行）|

## 本项目使用的专家

| 专家 | Slug | 部门 | 用途 |
|------|------|------|------|
| UI Designer | ui-designer | design | 页面设计与交互 |
| Frontend Developer | frontend-developer | engineering | Vanilla JS 前端 |
| Code Reviewer | code-reviewer | engineering | 代码审查 |
| Git Workflow Master | git-workflow-master | engineering | 分支策略 |
| API Tester | api-tester | testing | API 测试 |
| Database Optimizer | database-optimizer | engineering | 数据库优化 |
| Financial Analyst | financial-analyst | finance | 财务数据验证、三表一致性 |
| Investment Researcher | investment-researcher | finance | 投资框架设计、行业对比 |

## 使用示例

```text
# 数据库优化
agency_agents_load agent=database-optimizer task="分析 stock_analysis 库性能"

# 前端开发
agency_agents_load agent=frontend-developer task="实现股票对比表格"
agency_agents_load agent=ui-designer task="设计聊天界面"

# 财务分析
agency_agents_load agent=financial-analyst task="验证三表数据一致性"
agency_agents_load agent=investment-researcher task="设计行业同业对比框架"
```

## 已知限制

- **`agency_agents_delegate` 不可用**：返回 `"delegate_task requires a parent agent context"`。这是 Hermes 架构限制——主会话 Agent 不能派生子 Agent。替代方案：`agency_agents_load` 获取专家 Prompt，我化身专家直接执行。效果等同委托，速度更快。
- **分析类专家不建议 delegate**：Financial Analyst、Investment Researcher 等需要反复查数据交互的专家，delegate 模式不适用。直接 `load` + 手动按方法论执行更灵活。
