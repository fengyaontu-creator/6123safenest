# SafeNest

> CA6123 · Agentic AI and Applications
> Singapore rental Agentic assistant — multi-agent collaboration · three-layer guardrail · Human-in-the-Loop

---

## Assignment Deliverables — Quick Map for Graders

This table maps every Section-3 deliverable from the assignment brief to the concrete artefacts in this repo.

| # | Deliverable | Where to find it | Status |
|---|---|---|---|
| 1 | **Overview** — objective, motivation, agentic workflow | [README §Project Overview](#project-overview) + [docs/architecture.md](docs/architecture.md) + video slides 1-2 | ✅ |
| 2 | **Perceive stage** — prompt + context engineering | [agents/intake_agent.py](agents/intake_agent.py) (LLM-driven field extraction) + [guardrails/](guardrails/) (input filtering) | ✅ |
| 2-bonus | **Agentic RAG** | [tools/vector_store.py](tools/vector_store.py) + [agents/contract_compare.py](agents/contract_compare.py) — Chroma vector DB seeded with 4 official CEA standard templates; clauses retrieved via semantic search before deviation scoring | 🎁 **Bonus** |
| 3 | **Reason stage** — intent classification, task breakdown | [agents/orchestrator.py](agents/orchestrator.py) (`SequentialAgent → ParallelAgent → Synthesizer` topology) + [agents/intake_agent.py](agents/intake_agent.py) (intent routing for direct-rental vs agent-rental, rent-undecided vs rent-given, small-talk short-circuit) | ✅ |
| 4 | **Action stage** — tool-calling | All 4 specialists via `FunctionTool`: [location](agents/location_agent.py) (MRT/commute), [contract](agents/contract_agent.py) (RAG retrieval), [price](agents/price_agent.py) (CSV lookup), [risk](agents/risk_agent.py) (live data.gov.sg API + local fallback) | ✅ |
| 5 | **Learn stage** — in-context learning | `INTERNAL_JSON_OUTPUT_INSTRUCTION` in [agents/__init__.py](agents/__init__.py) + per-agent structured instructions ground every LLM call; Pydantic `AgentOutput` schema enforces output shape | ✅ |
| 5-bonus | **Agent Evaluation** | [tests/](tests/) — 175 automated tests across 14 files (no API key required for the deterministic path); [docs/evaluation_report.md](docs/evaluation_report.md) | 🎁 **Bonus** |
| 6 | **AI-Human interaction** | [agents/intake_agent.py](agents/intake_agent.py)::`IntakeRouterAgent` — when required fields are missing, the system asks targeted follow-up questions instead of guessing or failing; supports both CLI flags and web PDF upload | ✅ |
| 7 | **Responsible Agentic AI** — guardrails + testing | 3 layers in [guardrails/](guardrails/) wired into the intake router; 22 dedicated guardrail tests in [tests/test_guardrails.py](tests/test_guardrails.py) + 18 extended attack/benign cases in [tests/test_injection_cases.py](tests/test_injection_cases.py); full report in [docs/guardrail_report.md](docs/guardrail_report.md) | ✅ |
| 7-bonus | **Advanced guardrails** — prompt injection filtering, redacted PII | [guardrails/injection_filter.py](guardrails/injection_filter.py) (17 patterns, 5 categories) + [guardrails/pii_detector.py](guardrails/pii_detector.py) (Microsoft Presidio + custom Singapore NRIC recognizer) | 🎁 **Bonus** |
| 8 | **Conclusions** — per-member contributions, novelty, challenges | [MEMBER_CONTRIBUTIONS.md](MEMBER_CONTRIBUTIONS.md) — each member's PRs and modules, what was novel, what challenges we hit and how we resolved them | ✅ |

**Bonus features summary (per Appendix B):** Agentic RAG (#1), Agent Evaluation (#3), Advanced Guardrails (#6 — both injection filtering and PII redaction).

---

## Table of contents

- [Project Overview](#project-overview)
- [Architecture overview](#architecture-overview)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Assignment Deliverables — Quick Map for Graders](#assignment-deliverables--quick-map-for-graders) (above)
- [MEMBER_CONTRIBUTIONS.md](MEMBER_CONTRIBUTIONS.md) (per-member work + novelty + challenges)
- [Directory structure](#directory-structure)
- [Team roles](#team-roles)
- [Git collaboration workflow](#git-collaboration-workflow)
- [Task checklist](#task-checklist)
- [Risk quick-look](#risk-quick-look)
- [Key reminders](#key-reminders)

---

## Project Overview

SafeNest is a multi-agent assistant for the Singapore rental market. The user supplies a target address, an optional rent budget, and a contract PDF; the system dispatches four specialist agents in parallel and returns a single risk-rated report covering **commute, rent, contract, and agent legitimacy**, together with actionable negotiation suggestions.

**Pain points addressed**

- Lease contracts are dense; new tenants (especially international students) routinely miss unfair clauses around deposit, early termination, and repair liability.
- Real-estate agent quality varies; CEA registration status has to be cross-checked one agent at a time.
- Rental price information is fragmented; tenants lack an objective basis for negotiation.
- Commute time and neighbourhood amenities require manual comparison across multiple platforms.

Design rationale and key decisions are recorded in [plan.md](plan.md) (internal design log).

---

## Architecture overview

```
                        ┌──────────────────┐
   User Input  ───────▶ │  Guardrail-In    │  PII redaction + prompt-injection filter
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
                        │   Synthesizer    │  merged report + negotiation advice
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │   Scope Guard    │  out-of-scope refusal
                        └────────┬─────────┘
                                 ▼
                            Final Report
```

For an in-depth walkthrough including the four-stage `Perceive → Reason → Action → Learn` mapping, see [docs/architecture.md](docs/architecture.md).

---

## Tech stack

| Component        | Choice                                       |
| ----------- | ------------------------------------------ |
| LLM         | Gemini 2.5 Flash / Flash Lite (invoked via ADK; see [config.py](config.py)) |
| Agent framework  | **Google ADK (Python)** — `SequentialAgent` + `ParallelAgent` + `LlmAgent` |
| Vector store      | Chroma (local ONNX embeddings, no external API)                                     |
| PDF parsing    | pypdf + pdfplumber (two-tier: pypdf fast path, pdfplumber layout-aware fallback)                         |
| PII detection    | Regex-based with Microsoft Presidio integration when available                         |
| Observability        | ADK built-in tracing (OTel exporter intentionally disabled for Python 3.13 compatibility) |
| Dependency management | Poetry                                     |
| Testing        | pytest (175 tests, no API key required for the deterministic path)                                     |
| Interactive debugging | `adk web` (the browser-based debug UI shipped with ADK)       |

---

## Quick start

```bash
# 1. Install dependencies
poetry install

# 2. Install pre-commit hooks (run once per clone — blocks secrets / large files / merge markers)
pip install pre-commit
pre-commit install

# 3. Configure environment variables
cp .env.example .env
# Fill in GOOGLE_API_KEY (Gemini)
# Optional: DATAGOVSG_API_KEY (CEA salesperson lookup; the local CSV fallback works without it)

# 4. Run an end-to-end example via the CLI
poetry run python main.py \
  --address "123 Jurong West" \
  --rent 2000 \
  --contract data/sample_contract.pdf

# 5. Interactive browser session via the ADK web UI
poetry run adk web

# 6. Run the full test suite (175 tests, ~45 seconds, no API key needed)
poetry run pytest
```

> **Note on pre-commit**: every `git commit` runs the secrets scanner, large-file check, and merge-marker check. Do **not** bypass with `--no-verify` if a hook fails — fix the underlying issue and recommit. See [.pre-commit-config.yaml](.pre-commit-config.yaml).

---

## Directory structure

```
safenest/
├── README.md                       # maintained by all
├── plan.md                         # design log (all)
├── pyproject.toml                  # A + B
├── poetry.lock                     # A + B (generated by poetry install)
├── .env.example                    # all
├── .gitignore                      # A + B
├── main.py                         # A — CLI entry
├── config.py                       # A — configuration
│
├── logs/
│   └── app.log                     # runtime log (all)
│
├── agents/                         # A + B + C + D
│   ├── __init__.py
│   ├── orchestrator.py             # A
│   ├── location_agent.py           # A
│   ├── contract_agent.py           # B
│   ├── price_agent.py              # C
│   ├── risk_agent.py               # D
│   └── synthesizer.py              # A (B reviewer)
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
│   ├── csv_lookup.py               # C (D reviewer)
│   ├── vector_store.py             # B
│   └── cache.py                    # A
│
├── data/                           # C + D
│   ├── mrt_stations.json           # C
│   ├── listings.csv                # C
│   ├── cea_agents.csv              # D
│   ├── cea_standard_lease.pdf      # D (manually placed)
│   └── sample_contract.pdf         # D (manually placed)
│
├── tests/                          # all
│   ├── __init__.py
│   ├── test_location.py            # A
│   ├── test_contract.py            # B
│   ├── test_price.py               # C
│   ├── test_risk.py                # D
│   ├── test_guardrails.py          # B
│   ├── test_injection_cases.py     # B (Stretch)
│   └── test_integration.py         # B
│
├── evaluation/                     # D (Stretch)
│   ├── contract_test_cases.json    # D
│   └── eval_runner.py              # D (B reviewer)
│
└── docs/                           # C + D
    ├── architecture.md              # D
    ├── demo_script.md              # D
    ├── guardrail_report.md         # B + D (Stretch)
    ├── evaluation_report.md        # D (Stretch)
    └── screenshots/                # D
```

> Items added on top of the original iteration: `evaluation/`, `docs/architecture.md`, `docs/guardrail_report.md`, `docs/evaluation_report.md`, `tests/__init__.py`, `.gitignore` — all placeholders kept in for the Day 6–7 Stretch and Responsible-AI scoring. If we drop any of those, the placeholders can be removed.

---

## Team roles

| Role | Modules                          | Notes                                  |
| ---- | -------------------------------- | -------------------------------------- |
| A    | Orchestrator + Location Agent    | ADK skeleton + commute scoring         |
| B    | Contract Agent + Guardrails      | PDF parsing + Agentic RAG + 3-layer guardrail |
| C    | Price Agent + Mock data          | Rent comparison + dataset preparation  |
| D    | Risk Agent + Documentation       | CEA verification + report / screenshots |

---

## Git collaboration workflow

> **Iron rule: never commit code directly to `main`.** Each member works on their own branch and merges back into `main` via a Pull Request (PR). That way teammates can review, regressions can be reverted, and `main` is always demo-ready.

### 0. First-time clone (once per member)

```bash
# Clone the repo locally
git clone <repo-url>
cd 6123safenest

# Install dependencies
poetry install
```

### 1. Before writing code · sync with main

```bash
# Switch to main
git switch main

# Pull the latest code (a teammate may have just merged something)
git pull origin main
```

### 2. Create your own development branch

**Branch naming convention**: `<role>/<short-task>`, all lowercase, hyphen-separated.

```bash
# Examples
git switch -c A/orchestrator         # A — skeleton
git switch -c B/contract-pdf-parser  # B — PDF parsing
git switch -c C/listings-mock        # C — prepare mock data
git switch -c D/cea-agents-csv       # D — CEA registry
```

> One branch = one task. Once a task is merged into main, open a new branch for the next task.

### 3. Code → commit → push

```bash
# Check what you've changed
git status

# Stage the files (prefer naming them explicitly over `git add .`)
git add agents/contract_agent.py tests/test_contract.py

# Commit (write a clear message)
git commit -m "feat(contract): add PDF clause extraction"

# Push to GitHub (use -u the first time you push a branch)
git push -u origin B/contract-pdf-parser
```

**Recommended commit-message prefixes**

| Prefix    | Purpose            | Example                                |
| --------- | ------------------ | -------------------------------------- |
| `feat:`   | new feature        | `feat(price): add rent median calc`    |
| `fix:`    | bug fix            | `fix(pdf): handle empty page`          |
| `docs:`   | docs only          | `docs: update README quickstart`       |
| `test:`   | tests              | `test(risk): add CEA lookup test`      |
| `chore:`  | chores (deps etc.) | `chore: bump google-adk to 1.x`        |

### 4. Open a PR (after development)

1. After pushing, GitHub will show a green **Compare & pull request** prompt — click it.
2. Use a clear title; fill the body with this template:
   ```
   ## Changes
   - Implemented PDF clause extraction for the contract agent
   - Added two unit tests: deposit / early termination

   ## How to test
   poetry run pytest tests/test_contract.py

   ## Linked task
   README task checklist · Day 3-4 · Contract Agent item 2
   ```
3. Add a reviewer in the right-hand **Reviewers** panel (e.g. B's PR is reviewed by A).
4. **Don't self-merge.** Wait for review approval and CI to pass (if any) before merging.
5. After merging, locally:
   ```bash
   git switch main
   git pull origin main
   git branch -d B/contract-pdf-parser   # delete the merged local branch
   ```

### 5. FAQ

**Q: `git pull` reports a conflict — what now?**
A: Don't panic, don't force anything. Open the conflicted file; VS Code highlights `<<<<<<<`, `=======`, `>>>>>>>`. Pick "Accept Current" or "Accept Incoming", then `git add <file> && git commit`. If you're stuck, ping B in the group chat.

**Q: I accidentally wrote code on `main` — what now?**
A: Don't commit yet. Move the changes to a new branch:
```bash
git switch -c <role>/<task>   # uncommitted changes follow you
```
Then add / commit / push as usual.

**Q: How do I pull a teammate's latest code into my branch?**
A: Commit your own changes first, then:
```bash
git switch main
git pull origin main
git switch <your-branch>
git merge main
```

**Q: How often should I commit?**
A: Once per small feature. Don't sit on a week's worth of work in one commit. Push to your branch at least once a day so a laptop crash doesn't lose work.

### 6. Things to never do

- ❌ `git push origin main` directly
- ❌ `git push --force` (overwrites others' work)
- ❌ Commit `.env` (contains API keys)
- ❌ Commit large binaries / PDFs / videos to source (PDFs in `data/` are fine, but don't commit hundreds of MB)
- ❌ Force-push over a teammate's branch before their PR has been merged

---

## Task checklist

> Each task is tagged with the owner `[A/B/C/D]`; tick `[x]` when done. Self-check against the **Checkpoint** at the end of each day.

### Day 1–2 · Skeleton

**Repo / environment**
- [x] [A+B] Init Git repo + directory skeleton
- [x] [A+B] `pyproject.toml` Poetry dependencies
- [x] [A+B] `.env.example` template
- [x] [A+B] `poetry install` works, commit `poetry.lock`
- [x] [all] Clone repo + `poetry install` to verify environment parity

**ADK skeleton**
- [x] [A] `agents/orchestrator.py`: `SequentialAgent(ParallelAgent(4 sub-agents) → synthesizer)`
- [x] [A] 4 sub-agents as `LlmAgent` placeholders (return placeholder `AgentOutput`, no tools yet)
- [x] [A] `agents/synthesizer.py`: read 4 outputs from ADK session state, compose a report
- [x] [A] `main.py`: CLI entry (argparse for address / rent / contract path), invokes `Runner` to drive the root agent
- [x] [A] Verify the same agent runs in browser via `adk web`

**Mock data**
- [x] [C] `data/mrt_stations.json`: 10 MRT stations + NTU/CBD commute time + full metadata (PR #3)
- [x] [C] `data/listings.csv`: 20 listings (PR #3)
- [x] [D] `data/cea_agents.csv`: CEA registered agents (37,715 rows, PR #7)
- [x] [D] `data/cea_standard_lease/`: 5 official CEA standard lease PDFs (HDB / private / Compliance Checklist, PR #8)
- [x] [D] `data/sample_contract/Group A/`: test set v1 (sample `.docx` contract + explanatory MD, PR #8) — note it's `.docx`, not `.pdf`

**Day 2 Checkpoint**
- [x] `python main.py --address "..." --rent ... --contract data/sample_contract.pdf` runs end-to-end + `adk web` runs in browser
- [x] All mock data files in place with correct format

---

### Day 3–4 · Four agents in parallel

**Unified interface (Day 3 morning alignment)**
- [x] [A+B] Define `AgentInput` / `AgentOutput` Pydantic schema in `agents/__init__.py`
- [x] [all] Each agent strictly emits the schema

**A · Location Agent**
- [x] Read `data/mrt_stations.json` to compute commute time
- [x] Score surroundings (MRT distance / convenience-store density, mocked)
- [x] Output commute score + surroundings score + risk hints
- [x] `tests/test_location.py`: validate output format with a Jurong West input

**B · Contract Agent ★ scoring core**
- [x] `tools/pdf_parser.py`: pypdf + pdfplumber wrapper (PR #14)
- [x] `tools/vector_store.py`: build the CEA standard-lease knowledge base in Chroma (PR #15)
- [x] Clause extraction: deposit / early termination / repair liability / utilities (PR #20 commit 1, `agents/contract_clauses.py`)
- [x] Compare against CEA standard, flag deviations (PR #20 commit 2, `agents/contract_compare.py` RAG retrieval)
- [x] Output risky-clause list + severity scores (PR #20 commit 3, `agents/contract_risk.py`, low/medium/high detection across the 4 clause types)
- [x] `tests/test_contract.py`: end-to-end validation with the HDB standard template + a synthetic "predatory contract" (PR #20 commit 4, 11 tests)

**C · Price Agent**
- [x] Read `data/listings.csv`; filter comparable listings by area + unit type (PR #19, `lookup_comparable_listings`)
- [x] Compute rent median / mean / percentiles (PR #19, `compute_price_statistics`, with p25/p75)
- [x] LLM generates rent-reasonableness analysis + negotiation room (PR #19, LlmAgent + 3 `FunctionTool`s)
- [x] Output price score + comparable data + counter-offer suggestions (4-bucket verdict + numeric counter-offer)
- [x] `tests/test_price.py`: 6 tests (happy path + edge cases)

**D · Risk Agent**
- [x] `tools/csv_lookup.py::verify_cea_agent_status` calls the data.gov.sg API (PR #8)
- [x] `agents/risk_agent.py` real logic (PR #18, 729 lines + 60+25+15 weighted scoring)
- [x] Read `data/cea_agents.csv` for offline fallback (PR #18, `lookup_cea_local`, 37,715-row CEA registry)
- [x] LLM generates the risk-assessment summary (PR #18, LlmAgent + 3 `FunctionTool`s: verify / compute_score / generate_tips)
- [x] Output registration status + risk score + advice (4 status_label values: active/expired/not_found, with bilingual labels)
- [x] `tests/test_risk.py`: 27 tests covering lookup / verify / score / risk_tips / end-to-end

**Day 4 Checkpoint**
- [x] pytest **121/121** passing (intake 6 / location 5 / pdf_parser 11 / vector_store 9 / contract_clauses 13 / contract_compare 8 / contract_risk 20 / contract 11 / price 6 / risk 27 + others)
- [x] Outputs of all 4 agents conform to `AgentOutput`
- [x] B / C / D real agent unit tests all done (4 sub-agents promoted from placeholders to real logic)

---

### Day 5 · Integration day ★ must `git tag baseline-v1`

**Morning · wiring**
- [x] [A] All 4 agents wired into the Orchestrator, parallel scheduling working (PR #6)
- [x] [A+B] Synthesizer aggregates 4 `AgentOutput`s into a structured report (PR #6)
- [x] [A] Human-in-the-Loop node: `IntakeRouterAgent` asks polite follow-up questions when fields are missing + Web side supports PDF upload (PR #6/#9)

**Afternoon · Guardrail**
- [x] [B] `guardrails/pii_detector.py`: PII detection (NRIC / phone / email / PERSON), regex-based, gracefully degrades when Presidio unavailable
- [x] [B] `guardrails/injection_filter.py`: 17 regex patterns, 5 attack categories
- [x] [B] `guardrails/scope_guard.py`: 14 out-of-scope refusal patterns (legal / immigration / financial guarantee / medical / discrimination / NSFW)
- [x] [B] Guardrails wired into the `IntakeRouterAgent` entry point (injection + scope checked synchronously; PII written into `user_query_redacted` state for log/audit)

**End-to-end demo**
- [x] [all] Jurong West case runs the full flow (B verified `adk web adk_apps`; all 4 sub-agents + synthesizer produce real output)
- [x] [all] Report complete: commute ✅ + rent ✅ + contract ✅ + agent ✅ (4 sub-agents fully real, PR #18/#19/#20)
- [x] [B] Guardrail blocks prompt injection (17 patterns) + scope (14 patterns) + PII redaction; `tests/test_guardrails.py` 22 tests all pass
- [ ] [all] Negotiation-email draft (synthesizer now contains advice but no separate email; could be a polish item)

**Day 5 Checkpoint ★**
- [x] End-to-end demo < 3 minutes (deterministic fallback path 30 s; LLM path 10–20 s when healthy)
- [x] **`git tag baseline-v1` lock the version** (commit `0545d12`, pushed to origin)
- [x] [B] Integration tests [tests/test_integration.py](tests/test_integration.py) pass (PR #29, **13 e2e cases** + fixed the rent=None small-sample TypeError)

---

### Extras · engineering hygiene (not in the original plan)

- [x] [B] Extended `.gitignore`: ADK runtime / Chroma / IDE shared / OS (PR #10)
- [x] [B] Removed hard-coded API key from `tools/csv_lookup.py`, moved to `.env` (PR #11)
- [x] [B] pre-commit + detect-secrets + gitleaks — three-layer secret defence (PR #12)
- [x] [B] B's three personal branches cleaned up

> This is the hard evidence for **Responsible AI (25%)**: the repo has automated secret scanning, dependency hygiene, and a documented git workflow.

---

### Day 6–7 · Stretch (independent branches; revert if blocked)

**Priority 1 · Observability (ADK Trace + OpenTelemetry) [A] · half day**
- [-] Enable ADK built-in trace — **decided to disable**; Python 3.13 + OTel SDK 1.41 contextvars incompatibility triggers a tenacity retry storm (see [docs/architecture.md](docs/architecture.md) decision 7)
- [ ] Persist each run's trace to `logs/`
- [ ] Capture 5 trace screenshots into `docs/screenshots/`

**Priority 2 · Evaluation [D] · half day**
- [ ] `evaluation/contract_test_cases.json`: 10 contract-trap test cases (file exists but empty)
- [ ] `evaluation/eval_runner.py`: precision / recall (file exists but empty)
- [x] Output [docs/evaluation_report.md](docs/evaluation_report.md) (B rewrote, based on actual pytest output. **Currently 175/175** + per-file distribution across 14 test files)

**Priority 3 · Guardrail hardening [B] · half day**
- [x] Prompt-injection attack cases: [tests/test_guardrails.py](tests/test_guardrails.py) 10 base cases + [tests/test_injection_cases.py](tests/test_injection_cases.py) 18 extended cases (D contributed in PR #28; B adapted to the dict-or-None API)
- [x] Output [docs/guardrail_report.md](docs/guardrail_report.md) (B rewrote, 100% aligned with the actual 22 tests + implementation)

**Priority 4 · Agentic RAG [B] · 1 day**
- [ ] Iterative retrieval in the Contract Agent (multi-round retrieve → reason → re-retrieve)
- [ ] Compare detection rate vs single-pass RAG

**Priority 5 · CV vision detection [A] · 1 day · ⚠️ high risk**
- [ ] Day 6 morning quick validation: 3 listing photos + Gemini Flash vision
- [ ] Acceptance: per-image < 2000 tokens AND > 50% of preset questions answered
- [ ] If it misses, drop it

**Priority 6 · MCP wrapping · only if there's slack**

---

### Documentation / demo materials (whole-cycle · D leads)

- [x] [D] [docs/architecture.md](docs/architecture.md): architecture diagram + 7 design decisions (B already corrected tool names / risk dataset size / PII description to match the code)
- [x] [D] [docs/demo_script.md](docs/demo_script.md): 237-line demo script
- [ ] [D] `docs/screenshots/`: directory exists but **empty** — D needs to capture screenshots (per-agent output / guardrail blocks / final report)
- [ ] [D] Final report (consolidated into the assignment-prescribed format)

---

## Risk quick-look

| Risk             | Trigger                  | Response                                                |
| ---------------- | ------------------------ | ------------------------------------------------------- |
| ADK doesn't click | Day 2 skeleton won't run | Fall back to asyncio.gather + manual orchestration; lose framework bonus |
| Token budget overrun | Single run > $0.5    | Switch to Gemini Flash; drop CV; shorten prompts        |
| An agent stalls  | Still not running by Day 4 | LLM emits mock output directly; integration unblocks  |
| CV underperforms | Doesn't pass Day 6 validation | Drop it; baseline unaffected                       |
| Teammate behind  | From Day 3 onward         | B picks up the slack — Orchestrator + Contract first    |

---

## Key reminders

1. **Day 5 must end with `git tag baseline-v1`**; Stretch work happens on independent branches afterwards.
2. **Contract Agent is the scoring core**; most of the Responsible AI (25%) + Technical Competency (25%) evidence lives there.
3. **Aim for the full workflow, not a perfect agent.**
4. **Mock data isn't penalised**, but its quality dictates demo polish.
5. **C/D's docs and screenshots are bonus hard evidence — don't skip them.**

---

For NTU CA6123 coursework only; not for external distribution.
