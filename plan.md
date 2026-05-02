# SafeNest 开发计划

> CA6123 · Agentic AI and Applications  
> 团队 4 人 · 一周冲刺 · 进度起点：零

---

## 核心策略

**Baseline + Stretch 两层架构，Day 5 锁版本。**

- Baseline（Day 1–5）：确保端到端可跑、可演示的 MVP
- Stretch（Day 6–7）：在 Baseline 锁定后试错加分项，失败不影响交付

---

## 人员分工

| 角色 | 职责范围 | 说明 |
|------|--------|------|
| **A（有代码基础）** | Orchestrator + Location Agent | 搭 LangGraph 状态图骨架，Day 3 起开发 Location Agent |
| **B（你，有代码基础）** | Contract Agent + Guardrails + 集成 | 核心得分模块：PDF 解析 + Agentic RAG + 三层护栏 |
| **C（代码基础较弱）** | Price Agent + Mock 数据准备 | CSV 查表逻辑简单，同时负责准备全组 mock 数据 |
| **D（代码基础较弱）** | Risk Agent + 文档 / 演示材料 | CSV 查表 + CEA 名单核查，同时负责报告文档和截图 |

---

## 每日计划

### Day 1–2：搭骨架（全员）

**目标**：LangGraph 骨架跑通 + 全部 mock 数据就位

#### A + B（代码）
- [ ] 初始化 Git 仓库，建好目录结构（见下方）
- [ ] 创建 `pyproject.toml` / `requirements.txt`，统一 Python 环境
- [ ] 搭建 LangGraph 状态图：Orchestrator 节点 → 4 个空壳 Agent 节点 → Synthesizer 节点
- [ ] 跑通 hello world：输入一个地址，4 个 agent 各返回一句 placeholder，Synthesizer 拼成报告

#### C + D（数据 + 环境）
- [ ] 从 CEA 官网下载注册中介名单，清洗为 `data/cea_agents.csv`
- [ ] 手写 10 个新加坡地铁站坐标 + 到 NTU/CBD 的通勤时间 → `data/mrt_stations.json`
- [ ] 编写 20 条房源历史挂牌数据 → `data/listings.csv`（字段：地址、户型、面积、月租、发布日期）
- [ ] 找一份公开的 CEA 标准租约 PDF → `data/cea_standard_lease.pdf`
- [ ] 创建 1 份用于演示的样例租约 PDF → `data/sample_contract.pdf`（含故意设置的不公平条款）
- [ ] 写 `.env.example` 模板（LLM API key、LangSmith key 等）

#### Day 2 结束检查点
- [ ] `python main.py --address "123 Jurong West" --rent 2000` 能跑通，输出 placeholder 报告
- [ ] 所有 mock 数据文件就位且格式正确

---

### Day 3–4：四个 Agent 并行开发

**目标**：每个 Agent 独立可测试，输入输出接口统一

#### 统一接口约定

```python
# 每个 Agent 的输入输出 schema
class AgentInput(BaseModel):
    address: str
    rent: float
    contract_pdf: Optional[str] = None  # 文件路径
    budget: Optional[float] = None
    commute_destination: Optional[str] = None

class AgentOutput(BaseModel):
    agent_name: str
    score: float          # 0-10 分
    summary: str          # 一段话总结
    details: dict         # 结构化详情
    risks: list[str]      # 风险点列表
    recommendations: list[str]  # 建议列表
```

#### A → Location Agent
- [ ] 读取 `data/mrt_stations.json`，计算到目标地点的通勤时间
- [ ] 评估周边配套（地铁距离、便利店密度 — 用 mock 数据）
- [ ] 输出通勤评分 + 周边评分 + 风险提示
- [ ] 写单元测试：输入 Jurong West 地址，验证输出格式正确

#### B → Contract Agent
- [ ] 用 pypdf + pdfplumber 解析合同 PDF，提取文本
- [ ] 用 Chroma 建立 CEA 标准租约的向量知识库
- [ ] 实现条款提取：押金、提前终止、维修责任、水电费分担
- [ ] 实现对比逻辑：逐条与 CEA 标准对比，标记偏离项
- [ ] 输出风险条款列表 + 严重程度评分
- [ ] 写单元测试：用 sample_contract.pdf 验证能检出预设的不公平条款

#### C → Price Agent
- [ ] 读取 `data/listings.csv`，按区域 + 户型筛选可比房源
- [ ] 计算租金中位数、均值、分位数
- [ ] 用 LLM 生成租金合理性分析 + 可议价空间
- [ ] 输出价格评分 + 对比数据 + 议价建议
- [ ] 写单元测试：输入 Jurong West 2-bedroom $2000，验证输出

#### D → Risk Agent
- [ ] 读取 `data/cea_agents.csv`，核查输入的中介/房东姓名
- [ ] 判断是否在 CEA 注册名单中
- [ ] 用 LLM 生成风险评估总结
- [ ] 输出注册状态 + 风险评分 + 建议
- [ ] 写单元测试：输入一个在名单中的中介名，验证返回"已注册"

#### Day 4 结束检查点
- [ ] 每个 Agent 独立运行 `python -m agents.location --test` 通过
- [ ] 4 个 Agent 的输出格式统一符合 AgentOutput schema

---

### Day 5：集成日

**目标**：端到端跑通 → git tag baseline-v1

#### 上午：接线
- [ ] 4 个 Agent 接入 Orchestrator，并行调度跑通
- [ ] Synthesizer 汇总 4 个 AgentOutput，生成结构化报告
- [ ] 加入 Human-in-the-Loop 节点（合同条款确认 + 风险报告确认）

#### 下午：Guardrail + 演示
- [ ] 实现 Guardrail-In：PII 检测（Presidio）+ Prompt Injection 基础过滤
- [ ] 实现 Guardrail-Out：PII 脱敏 + 越权拒绝（法律建议拒绝模板）
- [ ] 用 Jurong West 演示用例跑一遍完整流程
- [ ] 确认输出报告内容完整、格式正确

#### Day 5 结束检查点
- [ ] **`git tag baseline-v1` 锁版本**
- [ ] 演示用例端到端 < 3 分钟
- [ ] 报告包含：通勤分析、租金对比、合同风险、中介核查、议价建议
- [ ] Guardrail 能拦截至少 1 个 PII + 1 个 prompt injection

---

### Day 6–7：Stretch 试错（按优先级排）

**原则：每个 Stretch 项独立分支开发，搞不定就 revert，不碰 baseline。**

| 优先级 | 项目 | 负责人 | 预计耗时 | 风险 |
|--------|------|--------|----------|------|
| 1 | Observability — 接 LangSmith | A | 半天 | 低：加几行代码 + 截图 |
| 2 | Evaluation — 10 case 测试集 | D | 半天 | 低：写测试数据 + 跑指标 |
| 3 | Guardrail 加强 — 5 个 injection 攻击用例 | B | 半天 | 低：构造测试用例 |
| 4 | Agentic RAG — Contract Agent 迭代检索 | B | 1 天 | 中：需要调 prompt |
| 5 | CV 视觉检测 — 房源图片分析 | A | 1 天 | **高：token + 效果不确定** |
| 6 | MCP 封装 | 有余力再说 | 1 天 | 中：学习成本 |

#### CV 视觉检测快速验证方案（Day 6 上午）
- [ ] 准备 3 张房源图片（含明显问题：墙面裂缝、漏水痕迹、老化设施）
- [ ] 用 Gemini Flash vision 跑一次，记录：token 消耗、识别准确度、延迟
- [ ] 判断标准：单张图 < 2000 tokens 且能识别出 > 50% 预设问题 → 继续开发
- [ ] 不达标 → 放弃，半天成本可接受

---

## 项目目录结构

```
safenest/
├── README.md
├── requirements.txt
├── .env.example
├── main.py                     # 入口：接收输入 → 跑完整流程
├── config.py                   # 配置：LLM 选择、路径、常量
│
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py         # LangGraph 状态图 + 调度逻辑
│   ├── location_agent.py
│   ├── contract_agent.py
│   ├── price_agent.py
│   ├── risk_agent.py
│   └── synthesizer.py          # 汇总报告 + 议价邮件
│
├── guardrails/
│   ├── __init__.py
│   ├── pii_detector.py         # Presidio PII 检测 + 脱敏
│   ├── injection_filter.py     # Prompt injection 过滤
│   └── scope_guard.py          # 越权拒绝（法律建议等）
│
├── tools/
│   ├── __init__.py
│   ├── pdf_parser.py           # pypdf + pdfplumber 封装
│   ├── csv_lookup.py           # CSV 数据查询工具
│   └── vector_store.py         # Chroma 向量库封装
│
├── data/
│   ├── mrt_stations.json       # 地铁站坐标 + 通勤时间
│   ├── listings.csv            # 历史挂牌数据
│   ├── cea_agents.csv          # CEA 注册中介名单
│   ├── cea_standard_lease.pdf  # CEA 标准租约（RAG 知识库）
│   └── sample_contract.pdf     # 演示用样例合同
│
├── tests/
│   ├── test_location.py
│   ├── test_contract.py
│   ├── test_price.py
│   ├── test_risk.py
│   ├── test_guardrails.py
│   └── test_injection_cases.py # 5 个 prompt injection 攻击用例
│
├── evaluation/
│   ├── contract_test_cases.json  # 10 个合同陷阱测试案例
│   └── eval_runner.py            # 跑精确率 / 召回率
│
└── docs/
    ├── architecture.md           # 架构说明
    ├── guardrail_report.md       # Guardrail 测试报告
    └── evaluation_report.md      # Agent 评估报告
```

---

## 技术栈速查

| 组件 | 选择 | 安装 |
|------|------|------|
| LLM | Gemini 2.0 Flash / GPT-4o-mini | `pip install google-generativeai` 或 `openai` |
| Agent 框架 | LangGraph | `pip install langgraph langchain-core` |
| 向量库 | Chroma | `pip install chromadb` |
| PDF 解析 | pypdf + pdfplumber | `pip install pypdf pdfplumber` |
| PII 检测 | Presidio | `pip install presidio-analyzer presidio-anonymizer` |
| 观测 | LangSmith | `pip install langsmith`（免费版） |
| 数据处理 | pandas | `pip install pandas` |

---

## 风险应对

| 风险 | 触发条件 | 应对 |
|------|----------|------|
| LangGraph 学不会 | Day 2 骨架跑不通 | 退化为纯函数调用 + 手动编排，放弃 LangGraph bonus |
| Token 预算超支 | 单次运行 > $0.5 | 换 Gemini Flash；砍 CV agent；缩短 prompt |
| 某个 Agent 做不出来 | Day 4 结束仍不能跑 | 用 LLM 直接生成 mock 输出，保证集成不阻塞 |
| CV 效果差 | Day 6 验证不达标 | 直接砍掉，不影响 Baseline |
| 队友进度落后 | Day 3 开始 | B（你）兜底，优先保 Orchestrator + Contract |

---

## 关键提醒

1. **Day 5 结束必须 `git tag`**。之后所有 Stretch 在独立分支开发，merge 前必须跑通演示用例
2. **Contract Agent 是拿分核心**。Responsible AI (25%) + Technical Competency (25%) 的素材主要来自这里
3. **不要追求完美的 agent，追求完整的 workflow**。老师评的是 agentic 设计的正确性，不是单个 agent 的效果
4. **Mock 数据 ≠ 扣分**。方案文档已经说了，评估核心是 workflow 设计，不是爬虫能力
5. **没有代码基础的队友也有高价值产出**：mock 数据质量直接决定演示效果，文档和截图是 bonus 的硬证据