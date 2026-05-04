"""General rental risk agent placeholder for the ADK team."""

from __future__ import annotations

from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from config import settings
from google.adk.agents import LlmAgent


def assess_risk(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    findings = ["Agent and landlord verification tools will be connected in Part D."]
    if request.address:
        findings.append("Address should be checked against viewing details and contract identity.")

    return AgentOutput(
        agent_name="risk_agent",
        summary="Risk screening is running in placeholder mode.",
        risk_level="unknown",
        findings=findings,
        recommendations=["Verify CEA salesperson registration before paying deposits."],
        data={"address": request.address},
    )


def create_risk_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="risk_agent",
        model=model,
        instruction=(
            "Screen rental scam and compliance risks. Part D will add CEA agent "
            "lookup and final policy checks.\n"
            + INTERNAL_JSON_OUTPUT_INSTRUCTION
        ),
        output_key="risk_output",
    )


risk_agent = create_risk_agent()


__all__ = ["assess_risk", "create_risk_agent", "risk_agent"]
