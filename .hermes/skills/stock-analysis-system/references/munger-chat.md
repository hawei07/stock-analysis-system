# 对话芒格系统

## API

| 方法 | 端点 | 作用 |
|------|------|------|
| GET | `/api/stock/<code>/munger-chat` | 获取历史 `[{id, role, content}]` |
| POST | `/api/stock/<code>/munger-chat` `{message}` | 发送消息，返回 `{reply, role}` |
| DELETE | `/api/stock/<code>/munger-chat?msg_id=N` | 删单条 |
| DELETE | `/api/stock/<code>/munger-chat` | 清空全部 |

## 消息处理流

1. 保存用户消息 → `munger_chats` (role=user)
2. URL检测 → `_fetch_url_content()` 抓取页面（Jina Reader，失败回退正则）
3. 搜索触发词（`?/怎么/为什么/查/搜索/新闻/看待`） → `_web_search()` + 前3条全文 `_fetch_url_content()`
4. 打包：财务摘要 + 最近10条对话 + URL内容 + 搜索结果
5. DeepSeek V4 Pro (temperature=0.3, max_tokens=1000)
6. 保存 → 返回

## System Prompt

完整芒格 418 行 Skill：
- 身份与记忆（Charlie Munger persona）
- 5 大心智模型（逆向/多元思维/Lollapalooza/能力圈/激励）
- 8 大决策启发式
- 表达 DNA（极短句/否定优先/向下类比/干燥幽默）
- 三筐分类格式 `{"score":0-100,"basket":"YES/NO/TOO_HARD"}`
- Agentic 工作流（先判断类型→做功课→用框架回答）
- 评分规则明细

## 前端

- 气泡聊天：芒格左灰底 🧠，用户右蓝底 👤
- 发送中：输入框禁用 + 三个点跳动动画
- ✕ 删除按钮：默认可见（20x20 圆，悬浮变红）
- 清空全部 → confirm → DELETE API
- 自动滚到底部

## 数据库

`munger_chats`:
```sql
CREATE TABLE munger_chats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(10) NOT NULL,
    role ENUM('user','munger') NOT NULL,
    content LONGTEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_stock_code (stock_code)
);
```

## 关键坑

- **max_tokens=600 不够**：芒格风格每句有数据，600 tokens 只能输出 ~165 字。改为 1000（~500 字）。
- **深度抓取是关键**：对话搜索也从仅标题改为抓取 Top 3 结果全文，分析质量从泛泛而谈跃升到具体数据支撑。
- **System Prompt 决定质量**：从 8 行对话指令改为完整 418 行芒格 Skill，三筐分析从此有类比/逆向思考/具体场景分拆。
