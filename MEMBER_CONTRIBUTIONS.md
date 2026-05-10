# Member Contributions — Group 2

This document maps each team member's concrete work to the source code and PR history in this repo. Numbers are taken from `git log` and the GitHub PR list, not estimates.

> All four members appear on screen and present their own segment in the video, in line with the rubric requirement.

---

## Per-member contributions

### Member A (GitHub: `hha233fyk`) — Team Lead · Orchestrator + Location Agent

- **Agent design workflow** (Sequential → Parallel → Synthesizer topology)
- [agents/orchestrator.py](agents/orchestrator.py) — root agent assembly, `run_offline_assessment()` and `run_offline_report()` entry points
- [agents/location_agent.py](agents/location_agent.py) — Haversine commute scoring against `data/mrt_stations.json`, surrounding-amenities heuristic, dual-path (deterministic + LlmAgent) implementation
- [agents/synthesizer.py](agents/synthesizer.py) — original report assembly logic
- [adk_apps/safenest/agent.py](adk_apps/safenest/agent.py) — ADK Web entry, PDF upload glue, session-state plumbing
- [main.py](main.py) — CLI entry
- Initial intake + orchestrator tests
- **Key PR:** #23 (orchestrator, AFC limit attempt, four sub-agents real, web entry, intake_agent skeleton)

### Member B (GitHub: `fengyaontu-creator` / `NoraFeng`) — Contract Agent + Guardrails + Integration

- [agents/contract_agent.py](agents/contract_agent.py) + [agents/contract_clauses.py](agents/contract_clauses.py) + [agents/contract_compare.py](agents/contract_compare.py) + [agents/contract_risk.py](agents/contract_risk.py) — full Contract Agent pipeline (PDF parse → clause extract → RAG comparison vs CEA standard → severity-rated risk summary)
- [tools/pdf_parser.py](tools/pdf_parser.py), [tools/vector_store.py](tools/vector_store.py) — pypdf + Chroma vector store seeded with 4 CEA template PDFs (the **Agentic RAG bonus**)
- [guardrails/](guardrails/) — three-layer guardrail system: injection_filter (17 patterns), pii_detector (Presidio + custom NRIC), scope_guard (14 patterns); wired into IntakeRouterAgent so violating queries cost zero LLM tokens
- [tests/test_integration.py](tests/test_integration.py) — 13 end-to-end integration cases
- [agents/synthesizer.py](agents/synthesizer.py)::`polish_with_llm()` — LLM polish layer that rewrites the deterministic fallback report into tenant-friendly markdown
- Cross-cutting bug fixes: synthesizer `{state_var}` template syntax, risk_agent `verified+empty record` branch, price_agent `n<5` p25/p75 degenerate verdict, dead-code cleanup
- Edge-case scenarios: direct-rental (no agent) detection, rent-undecided market-range output, English/Chinese small-talk short-circuit
- Pre-commit + detect-secrets + gitleaks setup; `.secrets.baseline` UTF-8 fix
- **Key PRs:** #14, #15, #20 (contract agent), #25 (guardrails wired), #26 (post-PR23 fixes), #27 (edge cases), #28 (incorporated D's WithGuardrail contributions), #29 (integration tests), #31 (synthesizer polish)

### Member C (GitHub: `Magnet0-o`) — Price Agent + Mock Data

- [agents/price_agent.py](agents/price_agent.py) — area extraction, comparable-listings lookup, price-statistics computation (median, p25, p75 with insufficient-data guard), rent-reasonableness verdict (4-bucket: excellent_deal / good_deal / fair_price / overpriced + `insufficient_data` and `market_range_only` for edge cases), dual-path implementation
- [data/listings.csv](data/listings.csv) — 20 hand-curated Singapore market listings
- [data/mrt_stations.json](data/mrt_stations.json) — 10 MRT stations with NTU/CBD commute times
- [tests/test_price.py](tests/test_price.py) — 6 happy-path and edge-case tests
- **Key PR:** #19 (price agent end-to-end)

### Member D (GitHub: `CHEN ZEYANG` / `ZYZY-Chen`) — Risk Agent + CEA Verification + Documentation

- [agents/risk_agent.py](agents/risk_agent.py) — full Risk Agent: live data.gov.sg API call (via [tools/csv_lookup.py](tools/csv_lookup.py)) with local CEA CSV fallback, 60+25+15 weighted scoring (registration / validity / data-source reliability), bilingual direct-landlord detection, NLP-based agent-name extraction from contract text, status-label translation
- [data/cea_agents.csv](data/cea_agents.csv) — 37,715-row CEA registry snapshot for offline verification
- [data/cea_standard_lease/](data/cea_standard_lease/) — 5 official CEA template PDFs used by the RAG store
- [docs/architecture.md](docs/architecture.md), [docs/demo_script.md](docs/demo_script.md) — slide deck and presentation script
- [tests/test_risk.py](tests/test_risk.py) — 27 tests covering API/CSV verification, scoring, risk-tip generation
- Original WithGuardrail branch (later partially incorporated into main via PR #28)
- **Key PRs:** #18 (risk agent + CEA dataset), #8 (data prep)

---

## What was novel

1. **Multi-agent cross-validation as the core value proposition.** A single price-agent or risk-agent in isolation can be fooled — a "great deal" from Price's perspective may actually be the bait of a scam that only Risk can catch. Our system surfaces this contradiction explicitly in the synthesized report so the renter sees *why* a low number is suspicious. (See video slide 7 — "Price Multi-Agent Value".)

2. **Bilingual direct-landlord detection.** Both Chinese ("直接找房东 / 无中介") and English ("no agent / private landlord") trigger a dedicated risk_agent branch that pivots from "ask for CEA reg" guidance to landlord-identity verification advice (SLA Land Inquiry, NRIC cross-check, named-bank-account requirement). This handles a real Singapore rental scenario the standard agent-driven flow ignores.

3. **Dual-path agent design.** Every specialist has both an LLM-driven `LlmAgent` (for natural conversation in the web UI) and a deterministic Python function (for tests, CLI, and as a fallback when Gemini is unavailable). Both paths share the same underlying tool functions, guaranteeing behavioural consistency. This is what lets us run 175 tests with no API key.

4. **Output polish layer for graceful degradation.** `polish_with_llm()` in [agents/synthesizer.py](agents/synthesizer.py) takes the deterministic-fallback report and runs one Gemini call to rewrite it as tenant-friendly markdown — but returns the raw report unchanged on any failure. The user always gets at least the technical report; on a good day they get the polished version.

---

## Key challenges and how we resolved them

### Challenge 1 — `afc_limiter` looked like it worked but didn't

We initially wrapped each sub-agent's `LlmAgent` with `generate_content_config=afc_limiter(2)` to cap automatic-function-calling iterations. Static inspection confirmed `agent.generate_content_config.automatic_function_calling.maximum_remote_calls = 2`, but runtime web-UI testing showed the SDK still logging `AFC max remote calls: 10`, with 100+ Gemini calls per query over 2.5 minutes.

**Root cause:** ADK runs its own outer tool-call loop in the flow layer; each pass is a fresh `generate_content` call from ADK's perspective, so SDK-level AFC bounds (which apply *within* one call) cannot bound ADK's outer loop.

**Resolution:** Removed the misleading helper (PR #26). The runaway-loop fix itself is tracked as follow-up work; for the demo we rely on the deterministic fallback path, which always produces a complete report in under a second.

### Challenge 2 — Integration with a parallel re-implementation by another member

Another member built a separate guardrail implementation on a `WithGuardrail` branch without coordinating. Roughly 70% of that work duplicated already-merged PR #25, but six pieces were genuinely valuable (notably real Microsoft Presidio engine wiring with custom NRIC `PatternRecognizer`, +65 phone format coverage, bilingual direct-landlord hints).

**Resolution:** PR #28 hand-ported the six valuable pieces, keeping our main branch's API surface stable; co-author credit was attributed in the commit. The duplicate / regressing parts (e.g., a `redact_pii` → `anonymize_pii` rename that would have broken `IntakeRouterAgent`) were deliberately not cherry-picked. The original branch was then retired.

### Challenge 3 — `.secrets.baseline` encoding bug across the team

The `.secrets.baseline` had been generated on Windows PowerShell with `>` redirection, which writes UTF-16 LE + BOM. `detect-secrets-hook` reads via Python's `json.load` (UTF-8), so every commit was failing pre-commit and several team members were stuck unable to push.

**Resolution:** PR #24 re-encoded the file as UTF-8 in place; PR #29 added a CI-friendly regeneration command in the README so the issue cannot recur (use `detect-secrets scan --baseline .secrets.baseline`, *never* `> .secrets.baseline`).

---

## Bonus features delivered (per Appendix B)

| # | Bonus feature | Where |
|---|---|---|
| 1 | **Agentic RAG** | Chroma vector store seeded with 4 official CEA templates; Contract Agent retrieves semantically similar CEA clauses before scoring deviation. See [tools/vector_store.py](tools/vector_store.py), [agents/contract_compare.py](agents/contract_compare.py). |
| 3 | **Agent Evaluation** | 175 automated tests across 14 files (deterministic path, no API key required); per-module results documented in [docs/evaluation_report.md](docs/evaluation_report.md). |
| 6 | **Advanced Guardrails** | Both subcategories: prompt injection filtering (17 patterns, 5 categories — instruction override / prompt extraction / token injection / jailbreak / role-play) **and** PII redaction (Microsoft Presidio with a custom Singapore NRIC `PatternRecognizer`). See [guardrails/](guardrails/). |
