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
    "synthesize_outputs",
    "synthesizer_agent",
]
