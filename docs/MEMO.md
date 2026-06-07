# ACP 備忘錄 — 起心動念、現況、未來

> 作者：Maki Chiba
> 日期：2026-06-07
> 狀態：MVP-1 剛跑通

---

## 起心動念

過去一年，我同時在管 7 個 AI agent：Claude Code、Codex CLI、Gemini CLI、Grok CLI、Perplexity Max、gemma4、SuperGrok。為了讓它們協作不打架，我做了一整套治理系統——memhall（記憶大廳）、mk-council（路由 + 斷路器）、ACE（多代理通訊協定）、civilization-stack（風險分級 + 強制異議）。

這套東西跑了半年，很好用。但有一天 terminal 大 crash，agent 中斷、memory 沒寫、git 沒 commit、context 消失。事後回想，我連「當時有幾個 agent 在跑」都答不出來。

然後我意識到：**我研究了一年「怎麼讓 agent 變強」，但從來沒認真想過「agent 變強之後怎麼管」。**

這不是模型問題，不是 agent 問題，不是 memory 問題。是治理問題。

同一天，我問了自己：「如果一家公司有 500 個員工、3000 個 agent，誰知道有幾個在跑？誰知道它們碰了什麼資料？誰知道花了多少錢？出事了能查到是哪一個嗎？」

答案是沒有人知道。目前沒有成熟的解決方案。

ACP 就是這個問題的起點。

---

## 這個專案不是什麼

- **不是另一個 agent framework**（LangChain / CrewAI / AutoGen 已經夠多了）
- **不是 observability tool**（LangSmith / OpenLIT / Arize 在做那層）
- **不是模型評測**（那是另一個領域）

## 這個專案是什麼

**AI Production Governance。**

當你的組織裡有一堆 AI agent 在跑，ACP 回答三個問題：

1. **有幾個？** — 你可能以為你有 5 個，其實有 22 個
2. **誰負責？** — 出事了找誰？目前答案是沒有人
3. **碰了什麼？** — 哪些 agent 能碰客戶資料？有人管嗎？

核心定位：**agent 的體檢報告，不是 agent 的大腦。**

---

## 現在能做什麼（MVP-1，2026-06-07）

### 主動探偵（最核心的功能）

```bash
acpctl scan
```

不需要任何人主動註冊。掃描你的機器，找出所有 AI 相關 entity。

8 種掃描器：
- Config 目錄（~/.claude、~/.codex、~/.gemini、~/.grok、~/.cursor 等）
- MCP server 清單（.mcp.json 裡每一個 tool）
- 執行中 process（ollama、Claude Desktop、MCP server）
- Docker container（含 AI 關鍵字的容器）
- 環境變數（ANTHROPIC_API_KEY、OPENAI_API_KEY 等，只偵測有沒有設，不讀值）
- Python packages（anthropic、openai、transformers、torch 等）
- npm packages（@google/gemini-cli、@openai/codex）
- VS Code extensions（GitHub Copilot、ChatGPT、Codeium）

### 6 分類系統

| Category | 定義 | 例子 |
|---|---|---|
| Agent | 會思考、做決策 | claude-code, codex-cli, gemini-cli |
| App | GUI 應用程式 | Claude Desktop, ChatGPT, Cursor |
| Tool | Agent 的手，被呼叫 | MCP servers (workspace, analytics, playwright) |
| Runtime | 跑 model 的基礎設施 | Ollama, vLLM |
| SDK | 裝在 code 裡的 AI 能力 | anthropic, openai, transformers |
| Extension | IDE 外掛 | GitHub Copilot, ChatGPT VS Code ext |

### 第一次 dogfood 結果

我自己的 MBP 掃出 **22 個 AI entities**，分布在 6 個分類。其中包括我已經不用的 Cursor、我忘了裝的 GitHub Copilot、以及 9 個 MCP tool server。

我自己都不知道自己有 22 個。

### 其他已完成的功能

- **Agent Registry** — 掃到的 entity 可以寫進 PostgreSQL
- **Audit Trail** — append-only 事件記錄，hash chain 防篡改
- **CLI 工具** — `acpctl scan / list / register / run / audit / gaps`
- **Web Dashboard** — http://localhost:8700/dashboard（暗色系，分類顯示）
- **Docker Compose** — 一行 `docker compose up` 啟動 API + DB

---

## 掃完之後能幹嘛（誠實版）

掃完看到清單，然後呢？老實說，現在能做的有限：

1. **砍掉不需要的** — 發現不用的工具，取消訂閱，省錢
2. **找出 shadow AI** — 發現不該存在的 MCP tool / 未經授權的 API key
3. **建立責任歸屬** — 拿清單問主管「這 23 個 entity 誰負責？」

ACP 現在是**體檢報告**——告訴你身體什麼狀況，但不會幫你吃藥。

---

## 未來要做什麼

### Phase 1：讓體檢報告更有用（1-2 個月）

- **assign owner** — 每個 entity 指定負責人（CLI + dashboard）
- **定期自動 scan** — cron job 定期掃描，發現新 entity 自動通知
- **diff report** — 這週 vs 上週，新增了什麼、消失了什麼
- **export** — 匯出 CSV / JSON，給主管做報告用

### Phase 2：從體檢到治療（2-4 個月）

- **policy engine** — 定義規則：「L2 以上資料只有指定 agent 能碰」
- **OTel 接入** — 接收 OpenTelemetry GenAI trace，追蹤 tool call / token cost
- **cost attribution** — 每個 agent 每月花了多少錢
- **stale detection** — 自動偵測超過 N 天沒 heartbeat 的 agent，建議退役

### Phase 3：從治療到免疫（4-6 個月）

- **admission controller** — 在 agent 呼叫 tool 之前，根據 policy 攔截或放行
- **cross-machine scan** — 掃描整個團隊的機器（需要 agent 安裝在每台機器）
- **org-level dashboard** — 全組織的 AI inventory + 治理狀態一覽
- **compliance report** — EU AI Act / 內部稽核用的報告生成

### 更遠的未來

- **agent identity standard** — 跨供應商的 agent 身份標準（對齊 NIST AI Agent Standards Initiative）
- **OTel GenAI governance extension** — 在 OTel 標準上擴充 governance 欄位
- **marketplace** — 社群貢獻的 scanner rules（新的 AI tool 出現就有人寫偵測規則）

---

## 為什麼是我

1. **我已經在 production 跑了半年的多 agent 治理系統** — memhall、mk-council、ACE、civilization-stack 不是理論，是每天在用的東西
2. **我的七位一體本身就是 6 家不同供應商** — 天然 vendor-agnostic
3. **PM + 系統架構 + 企業 AI 落地** — 我站在技術和商業的交叉點
4. **我有內容資產** — blog.chibakuma.com，邊做邊寫，每個功能就是一篇文章

## 為什麼是現在

- Forrester 確認 Agent Control Plane 是獨立產品類別（79% 廠商認可、40% 已收到 RFP）
- EU AI Act 2026-08 生效，要求 audit trail + human oversight
- Microsoft 已推 Agent 365 + OSS Toolkit，GitHub Enterprise AI Controls 已 GA
- 但**沒有一個方案覆蓋 registry + permissions + audit + multi-vendor 的完整組合**
- 開發者社群明顯偏好 OSS / self-hosted

窗口正在關閉，但還沒關上。

---

## 一句話

> **全世界都在研究怎麼造更好的 AI。但真正缺的是：怎麼營運一個 AI 組織。**

---

*這份備忘錄寫於 ACP 的第一天。第一次 scan 掃出 22 個 entity，0 個有 owner。*
