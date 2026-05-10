"""Report synthesizer for SafeNest agent outputs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agents import AgentOutput
from config import settings
from google.adk.agents import LlmAgent


RISK_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def synthesize_outputs(outputs: Iterable[AgentOutput | dict[str, Any]]) -> AgentOutput:
    parsed = [item if isinstance(item, AgentOutput) else AgentOutput(**item) for item in outputs]
    if not parsed:
        return AgentOutput(
            agent_name="synthesizer",
            summary="No agent outputs were available.",
            risk_level="unknown",
        )

    overall = max((item.risk_level for item in parsed), key=lambda value: RISK_RANK[value])
    scored = [item.score for item in parsed if item.score is not None]
    score = round(sum(scored) / len(scored), 1) if scored else None

    findings: list[str] = []
    evidence: list[str] = []
    recommendations: list[str] = []
    for item in parsed:
        findings.extend(f"{item.agent_name}: {finding}" for finding in item.findings)
        evidence.extend(item.evidence)
        recommendations.extend(item.recommendations)

    unique_recommendations = list(dict.fromkeys(recommendations))
    return AgentOutput(
        agent_name="synthesizer",
        summary=f"Overall rental risk is {overall}. Review the findings before committing funds.",
        risk_level=overall,
        score=score,
        findings=findings,
        evidence=list(dict.fromkeys(evidence)),
        recommendations=unique_recommendations,
        data={"agents": [item.agent_name for item in parsed]},
    )


def format_report(output: AgentOutput) -> str:
    score = f"{output.score}/100" if output.score is not None else "not scored"
    lines = [
        "# SafeNest Rental Assessment",
        "",
        f"Overall risk: {output.risk_level}",
        f"Score: {score}",
        "",
        output.summary,
        "",
        "## Findings",
    ]
    lines.extend(f"- {finding}" for finding in output.findings)
    if output.recommendations:
        lines.extend(["", "## Recommendations"])
        lines.extend(f"- {item}" for item in output.recommendations)
    return "\n".join(lines)


_POLISH_INSTRUCTION = """\
Rewrite the following Singapore rental risk report so a tenant can read \
it easily. Strict rules:
- Group findings by section: Location, Contract, Price, Agent.
- Use emoji section headers: 📍 Location, 📄 Contract, 💰 Price, 🛡 Agent.
- Keep ALL numbers, scores, and SGD amounts EXACTLY as in the original — \
do not invent, round, or paraphrase any figure.
- Drop technical labels like "[FLAG]", "[OK]", "agent_name:", and CLI \
flags like "--agent-name" or "--agent-reg-no".
- Use clear bullet points; bold key terms with markdown.
- Keep the "Overall risk: ... Score: ..." line near the top.
- Keep recommendations as a numbered list under a "## ✅ Next Steps" header.
- Output valid markdown only, no preamble, no meta-commentary, no \
explanation about what you changed.
- Maximum 400 words total.

Original report:

"""


def polish_with_llm(raw_report: str) -> str:
    """Rewrite a deterministic-format rental report into tenant-friendly markdown.

    Single Gemini call (~3-5 sec). On any failure — missing API key, network
    error, parsing issue, model unavailable — returns ``raw_report`` unchanged
    so the caller never gets a worse result than what they passed in.

    The polish layer is a no-op safety net for the deterministic fallback
    path; tests / CLI deterministic mode can keep calling format_report
    directly without invoking the LLM.
    """

    if not raw_report or not raw_report.strip():
        return raw_report

    try:
        import os

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return raw_report

        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.synthesizer_model,
            contents=_POLISH_INSTRUCTION + raw_report,
        )
        polished = (response.text or "").strip()
        return polished if polished else raw_report
    except Exception:
        # Any failure — silently fall back. The caller already had a usable
        # (if technical-looking) report.
        return raw_report


def create_synthesizer_agent(model: str = settings.synthesizer_model) -> LlmAgent:
    return LlmAgent(
        name="synthesizer",
        model=model,
        instruction=(
            "Combine the four specialist outputs from session state into a "
            "single tenant-facing rental risk report.\n\n"
            "Location agent output: {location_output}\n"
            "Contract agent output: {contract_output}\n"
            "Price agent output: {price_output}\n"
            "Risk agent output: {risk_output}\n\n"
            "If any output is missing or marked unavailable, explicitly mark "
            "that section as unavailable instead of failing.\n\n"
            "Produce a concise report with an overall risk level, key "
            "evidence from each specialist, and practical next actions."
        ),
        output_key="final_report",
    )


synthesizer_agent = create_synthesizer_agent()


__all__ = [
    "create_synthesizer_agent",
    "format_report",
    "polish_with_llm",
    "synthesize_outputs",
    "synthesizer_agent",
]
