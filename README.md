# SafeNest

> CA6123 · Agentic AI and Applications
> 新加坡租房 Agentic 助手 — 多 Agent 协同 · 三层 Guardrail · Human-in-the-Loop

## 目录

- [项目简介](#项目简介)
- [架构总览](#架构总览)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [团队分工](#团队分工)
- [Git 协作流程](#git-协作流程)
- [任务清单](#任务清单)
- [风险快查](#风险快查)
- [关键提醒](#关键提醒)

---

## 项目简介

SafeNest 是一个面向新加坡租房场景的多智能体助手。用户输入目标地址、预算、合同 PDF，系统并行调度 4 个专业 Agent，输出一份覆盖 **通勤 / 租金 / 合同 / 中介风险** 的综合报告，并附带可直接发送的议价邮件草稿。

**解决的痛点**

- 合同条款复杂，留学生易踩"不公平条款"陷阱（押金、提前终止、维修责任）
- 中介质量参差不齐，CEA 注册状态需要逐个核查
- 区域租金透明度低，缺少议价依据
- 通勤时间、周边配套需要跨平台手动比对

设计思路与决策详见 [plan.md](plan.md)。

---

## 架构总览

```
                        ┌──────────────────┐
   User Input  ───────▶ │  Guardrail-In    │  PII 检测 + Prompt Injection 过滤
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │   Orchestrator   │  ADK SequentialAgent
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │  ParallelAgent   │  ADK ParallelAgent
                        └─┬──────┬────┬────┴─┐
                          ▼      ▼    ▼      ▼
                    ┌────────┐┌──────┐┌─────┐┌──────┐
                    │Location││Contr.││Price││Risk  │
                    │  (A)   ││  (B) ││ (C) ││ (D)  │
                    └───┬────┘└──┬───┘└──┬──┘└──┬───┘
                        └────────┴───┬───┴──────┘
                                     ▼
                        ┌──────────────────┐
                        │   Synthesizer    │  汇总报告 + 议价邮件
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │  Guardrail-Out   │  PII 脱敏 + 越权拒绝
                        └────────┬─────────┘
                                 ▼
                            Final Report
```

---

## 技术栈

| 组件        | 选择                                       |
| ----------- | ------------------------------------------ |
| LLM         | Gemini 2.0 Flash（通过 ADK 调用）          |
| Agent 框架  | **Google ADK (Python)**                    |
| 向量库      | Chroma                                     |
| PDF 解析    | pypdf + pdfplumber                         |
| PII 检测    | Microsoft Presidio                         |
| 观测        | ADK 内置 trace + OpenTelemetry             |
| 数据处理    | pandas                                     |
| 依赖管理    | Poetry                                     |
| 测试        | pytest                                     |
| 交互调试    | `adk web`（ADK 自带的浏览器调试 UI）       |

---

## 快速开始

```bash
# 1. 安装依赖
poetry install

# 2. 配置环境变量
cp .env.example .env
# 填入 GOOGLE_API_KEY（Gemini）

# 3. 跑一个示例（CLI）
poetry run python main.py \
  --address "123 Jurong West" \
  --rent 2000 \
  --contract data/sample_contract.pdf

# 4. 浏览器交互调试（ADK 自带）
poetry run adk web

# 5. 跑测试
poetry run pytest
```

---

## 目录结构

```
safenest/
├── README.md                       # 全员维护
├── plan.md                         # 决策文档（全员）
├── pyproject.toml                  # A + B 配置
├── poetry.lock                     # A + B 配置（poetry install 生成）
├── .env.example                    # 全员维护
├── .gitignore                      # A + B
├── main.py                         # A 入口
├── config.py                       # A 配置
│
├── logs/
│   └── app.log                     # 全员日志（运行时生成）
│
├── agents/                         # A + B + C + D
│   ├── __init__.py
│   ├── orchestrator.py             # A
│   ├── location_agent.py           # A
│   ├── contract_agent.py           # B
│   ├── price_agent.py              # C
│   ├── risk_agent.py               # D
│   └── synthesizer.py              # A (B review)
│
├── guardrails/                     # B
│   ├── __init__.py
│   ├── pii_detector.py             # B
│   ├── injection_filter.py         # B
│   └── scope_guard.py              # B
│
├── tools/                          # A + B
│   ├── __init__.py
│   ├── pdf_parser.py               # B
│   ├── csv_lookup.py               # C (D review)
│   ├── vector_store.py             # B
│   └── cache.py                    # A
│
├── data/                           # C + D
│   ├── mrt_stations.json           # C
│   ├── listings.csv                # C
│   ├── cea_agents.csv              # D
│   ├── cea_standard_lease.pdf      # D（手动放置）
│   └── sample_contract.pdf         # D（手动放置）
│
├── tests/                          # 全员
│   ├── __init__.py
│   ├── test_location.py            # A
│   ├── test_contract.py            # B
│   ├── test_price.py               # C
│   ├── test_risk.py                # D
│   ├── test_guardrails.py          # B
│   ├── test_injection_cases.py     # B（Stretch）
│   └── test_integration.py         # B
│
├── evaluation/                     # D（Stretch）
│   ├── contract_test_cases.json    # D
│   └── eval_runner.py              # D (B review)
│
└── docs/                           # C + D
    ├── architecture.md              # D
    ├── demo_script.md              # D
    ├── guardrail_report.md         # B + D（Stretch）
    ├── evaluation_report.md        # D（Stretch）
    └── screenshots/                # D
```

> 与最初迭代相比额外加的：`evaluation/`、`docs/architecture.md`、`docs/guardrail_report.md`、`docs/evaluation_report.md`、`tests/__init__.py`、`.gitignore`——都是为 Day 6–7 Stretch 和 Responsible AI 评分留的占位，不打算做的可以直接删。

---

## 团队分工

| 角色 | 负责模块                        | 说明                                  |
| ---- | ------------------------------- | ------------------------------------- |
| A    | Orchestrator + Location Agent   | ADK 骨架 + 通勤评估                   |
| B    | Contract Agent + Guardrails     | PDF 解析 + Agentic RAG + 三层护栏     |
| C    | Price Agent + Mock 数据         | 租金对比 + 全组数据准备               |
| D    | Risk Agent + 文档演示           | CEA 核查 + 报告 / 截图                |

---

## Git 协作流程

> **铁律：永远不要直接在 `main` 分支上写代码。** 每个人在自己的分支上开发，写完通过 Pull Request (PR) 合回 `main`。这样别人能 review、出问题能回滚、`main` 永远是可演示的。

### 0. 第一次拉代码（每人只做一次）

```bash
# 把仓库 clone 到本地
git clone <仓库地址>
cd 6123safenest

# 装依赖
poetry install
```

### 1. 每次开始写代码前 · 同步 main

```bash
# 切到 main 分支
git switch main

# 拉最新代码（队友可能合了新东西进来）
git pull origin main
```

### 2. 创建自己的开发分支

**分支命名规则**：`<角色>/<任务简述>`，全小写、用短横线连接。

```bash
# 示例
git switch -c A/orchestrator         # A 做骨架
git switch -c B/contract-pdf-parser  # B 做 PDF 解析
git switch -c C/listings-mock        # C 准备 mock 数据
git switch -c D/cea-agents-csv       # D 整理 CEA 名单
```

> 一个分支只做一个任务。任务完成合进 main 后，下个任务再开新分支。

### 3. 写代码 → 提交 → 推送

```bash
# 看看自己改了哪些文件
git status

# 把要提交的文件加到暂存区（推荐显式指定，不要 git add .）
git add agents/contract_agent.py tests/test_contract.py

# 提交（commit message 写清楚做了什么）
git commit -m "feat(contract): add PDF clause extraction"

# 推送到 GitHub（第一次推送某个分支要加 -u）
git push -u origin B/contract-pdf-parser
```

**Commit message 推荐前缀**

| 前缀     | 用途           | 例子                                  |
| -------- | -------------- | ------------------------------------- |
| `feat:`  | 新功能         | `feat(price): add rent median calc`   |
| `fix:`   | 修 bug         | `fix(pdf): handle empty page`         |
| `docs:`  | 改文档         | `docs: update README quickstart`      |
| `test:`  | 加测试         | `test(risk): add CEA lookup test`     |
| `chore:` | 杂活（依赖等） | `chore: bump google-adk to 1.x`       |

### 4. 提 PR（开发完成后）

1. 推送完成后，GitHub 仓库页面会出现绿色提示 **Compare & pull request**，点它
2. 标题写清楚做了什么，正文按下面模板填：
   ```
   ## 改动内容
   - 实现了 contract agent 的 PDF 条款提取
   - 加了 push deposit / 提前终止 两个 unit test

   ## 怎么测
   poetry run pytest tests/test_contract.py

   ## 关联任务
   README 任务清单 · Day 3-4 · Contract Agent 第 2 项
   ```
3. 在右侧 **Reviewers** 指定一个队友 review（比如 B 的 PR 让 A review）
4. **不要自己点 Merge**，等 review 通过、CI 跑过（如果有）再合
5. 合完后在本地：
   ```bash
   git switch main
   git pull origin main
   git branch -d B/contract-pdf-parser   # 删除已合并的本地分支
   ```

### 5. 常见问题

**Q: `git pull` 报冲突怎么办？**
A: 不要慌、不要硬来。打开冲突文件，VS Code 会高亮 `<<<<<<<`、`=======`、`>>>>>>>`，选"Accept Current"或"Accept Incoming"，确认后 `git add 冲突文件 && git commit`。搞不定就在群里 @B。

**Q: 我不小心在 `main` 上写了代码怎么办？**
A: 别 commit，先把改动转到新分支：
```bash
git switch -c <角色>/<任务名>   # 当前未提交的改动会跟着过来
```
然后正常 add / commit / push。

**Q: 我要拉队友的最新代码到我的分支怎么办？**
A: 先 commit 自己的改动，然后：
```bash
git switch main
git pull origin main
git switch <你的分支>
git merge main
```

**Q: 我应该多久提一次 commit？**
A: 一个小功能完成就提一次。不要憋一周一个大 commit。每天至少 push 一次到自己的分支，免得电脑炸了代码丢了。

### 6. 绝对不要做的事

- ❌ 直接 `git push origin main`
- ❌ `git push --force`（会覆盖别人的工作）
- ❌ 把 `.env` 提交到仓库（里面有 API key）
- ❌ 把大文件、PDF、视频加到代码 commit 里（PDF 放 `data/` 是 OK 的，但别 commit 几百 MB 的东西）
- ❌ 在别人的 PR 没合并前，把别人的分支 force push 掉

---

## 任务清单

> 每条任务标注负责人 `[A/B/C/D]`，完成就 `[x]` 一项。每天结束对照 **Checkpoint** 自检。

### Day 1–2 · 搭骨架

**仓库 / 环境**
- [x] [A+B] 初始化 Git 仓库 + 目录骨架
- [x] [A+B] `pyproject.toml` 配 Poetry 依赖
- [x] [A+B] `.env.example` 模板
- [ ] [A+B] `poetry install` 跑通，提交 `poetry.lock`
- [ ] [全员] clone 仓库 + `poetry install` 验证环境一致

**ADK 骨架**
- [ ] [A] `agents/orchestrator.py`：`SequentialAgent(ParallelAgent(4 sub-agents) → synthesizer)`
- [ ] [A] 4 个 sub-agent 用 `LlmAgent` 占位（返回 placeholder `AgentOutput`，先不接工具）
- [ ] [A] `agents/synthesizer.py`：从 ADK session state 读取 4 份输出，拼成一段报告
- [ ] [A] `main.py`：CLI 入口（argparse 接收 address / rent / contract 路径），调用 `Runner` 跑 root agent
- [ ] [A] 验证 `adk web` 能在浏览器里跑通同一个 agent

**Mock 数据**
- [ ] [C] `data/mrt_stations.json`：10 个新加坡地铁站 + 到 NTU/CBD 通勤时间
- [ ] [C] `data/listings.csv`：20 条房源（地址 / 户型 / 面积 / 月租 / 发布日期）
- [ ] [D] `data/cea_agents.csv`：从 CEA 官网清洗注册中介名单
- [ ] [D] `data/cea_standard_lease.pdf`：找一份公开 CEA 标准租约
- [ ] [D] `data/sample_contract.pdf`：手造样例合同（含故意不公平条款）

**Day 2 Checkpoint**
- [ ] `python main.py --address "123 Jurong West" --rent 2000` 输出 placeholder 报告
- [ ] 全部 mock 数据文件就位，格式正确

---

### Day 3–4 · 四 Agent 并行开发

**统一接口（Day 3 上午对齐）**
- [ ] [A+B] 在 `agents/__init__.py` 定义 `AgentInput` / `AgentOutput` Pydantic schema
- [ ] [全员] 各 Agent 严格按 schema 输出

**A · Location Agent**
- [ ] 读取 `data/mrt_stations.json` 计算通勤时间
- [ ] 评估周边配套（地铁距离 / 便利店密度，用 mock）
- [ ] 输出通勤评分 + 周边评分 + 风险提示
- [ ] `tests/test_location.py`：Jurong West 输入验证输出格式

**B · Contract Agent ★ 拿分核心**
- [ ] `tools/pdf_parser.py`：pypdf + pdfplumber 封装
- [ ] `tools/vector_store.py`：Chroma 建 CEA 标准租约知识库
- [ ] 条款提取：押金 / 提前终止 / 维修责任 / 水电分担
- [ ] 与 CEA 标准对比，标记偏离项
- [ ] 输出风险条款列表 + 严重程度评分
- [ ] `tests/test_contract.py`：用 sample_contract.pdf 验证检出预设陷阱

**C · Price Agent**
- [ ] 读取 `data/listings.csv`，按区域 + 户型筛选可比房源
- [ ] 计算租金中位数 / 均值 / 分位数
- [ ] LLM 生成租金合理性分析 + 议价空间
- [ ] 输出价格评分 + 对比数据 + 议价建议
- [ ] `tests/test_price.py`：Jurong West 2-bedroom $2000 验证

**D · Risk Agent**
- [ ] 读取 `data/cea_agents.csv` 核查中介/房东姓名
- [ ] 判断是否在 CEA 注册名单
- [ ] LLM 生成风险评估总结
- [ ] 输出注册状态 + 风险评分 + 建议
- [ ] `tests/test_risk.py`：已注册中介名验证返回"已注册"

**Day 4 Checkpoint**
- [ ] 每个 Agent 单测通过
- [ ] 4 个 Agent 输出统一符合 `AgentOutput` schema

---

### Day 5 · 集成日 ★ 必须 `git tag baseline-v1`

**上午 · 接线**
- [ ] [A] 4 Agent 接入 Orchestrator，并行调度跑通
- [ ] [A+B] Synthesizer 汇总 4 个 `AgentOutput` 生成结构化报告
- [ ] [A] Human-in-the-Loop 节点：合同条款确认 + 风险报告确认

**下午 · Guardrail**
- [ ] [B] `guardrails/pii_detector.py`：Presidio PII 检测（IC、电话、邮箱）
- [ ] [B] `guardrails/injection_filter.py`：基础 Prompt Injection 过滤
- [ ] [B] `guardrails/scope_guard.py`：越权拒绝（法律建议拒绝模板）
- [ ] [B] Guardrail 接入 Orchestrator 入口 / 出口

**端到端演示**
- [ ] [全员] Jurong West 用例跑完整流程
- [ ] [全员] 报告完整：通勤 + 租金 + 合同 + 中介 + 议价
- [ ] [B] Guardrail 拦截至少 1 个 PII + 1 个 prompt injection

**Day 5 Checkpoint ★**
- [ ] 端到端演示 < 3 分钟
- [ ] **`git tag baseline-v1` 锁版本**
- [ ] [B] 集成测试 `tests/test_integration.py` 通过

---

### Day 6–7 · Stretch（独立分支，搞不定就 revert）

**优先级 1 · 观测 (ADK Trace + OpenTelemetry) [A] · 半天**
- [ ] 启用 ADK 内置 trace（`adk web` 会自动展示，CLI 跑则用 OTel exporter 输出到 stdout / 文件）
- [ ] 把每次 run 的 trace 持久化到 `logs/`
- [ ] 截图 5 个 trace 案例存 `docs/screenshots/`

**优先级 2 · Evaluation [D] · 半天**
- [ ] `evaluation/contract_test_cases.json`：10 个合同陷阱测试案例
- [ ] `evaluation/eval_runner.py`：跑精确率 / 召回率
- [ ] 输出 `docs/evaluation_report.md`

**优先级 3 · Guardrail 加强 [B] · 半天**
- [ ] `tests/test_injection_cases.py`：5 个 prompt injection 攻击用例
- [ ] 输出 `docs/guardrail_report.md`（含拦截率）

**优先级 4 · Agentic RAG [B] · 1 天**
- [ ] Contract Agent 迭代检索（多轮 retrieve → reason → re-retrieve）
- [ ] 对比单轮 RAG 的检出率提升

**优先级 5 · CV 视觉检测 [A] · 1 天 · ⚠️ 高风险**
- [ ] Day 6 上午快速验证：3 张房源图 + Gemini Flash vision
- [ ] 判断标准：单图 < 2000 tokens 且识别 > 50% 预设问题
- [ ] 不达标 → 直接砍掉

**优先级 6 · MCP 封装 · 有余力再说**

---

### 文档 / 演示物料（贯穿全周期 · D 主导）

- [ ] [D] `docs/architecture.md`：架构图 + 设计决策说明
- [ ] [D] `docs/demo_script.md`：3 分钟演示脚本（按时间轴）
- [ ] [D] `docs/screenshots/`：每个 Agent 输出截图 + ADK trace + Guardrail 拦截
- [ ] [D] 最终报告（按作业要求格式整合）

---

## 风险快查

| 风险             | 触发条件             | 应对                                          |
| ---------------- | -------------------- | --------------------------------------------- |
| ADK 学不会       | Day 2 骨架跑不通     | 退化为 asyncio.gather 并行 + 手动编排，放弃框架 bonus |
| Token 预算超支   | 单次运行 > $0.5      | 换 Gemini Flash；砍 CV；缩短 prompt           |
| 某 Agent 难产    | Day 4 仍不能跑       | LLM 直接生成 mock 输出，保证集成不阻塞        |
| CV 效果差        | Day 6 验证不达标     | 直接砍，不影响 Baseline                       |
| 队友进度落后     | Day 3 起             | B 兜底，优先保 Orchestrator + Contract        |

---

## 关键提醒

1. **Day 5 结束必须 `git tag baseline-v1`**，之后 Stretch 在独立分支
2. **Contract Agent 是拿分核心**，Responsible AI (25%) + Technical Competency (25%) 主要素材都在这里
3. **追求完整 workflow，不追求完美 agent**
4. **Mock 数据不扣分**，但质量决定演示效果
5. **C/D 的文档和截图是 bonus 硬证据，不可省**

---

仅用于 NTU CA6123 课程作业，不对外发布。
