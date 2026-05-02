"""Price agent placeholder for the ADK team."""

from __future__ import annotations

from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from config import settings
from google.adk.agents import LlmAgent


def assess_price(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    findings = ["Price benchmark tools will be connected in Part C."]
    if request.rent is not None:
        findings.append(f"Input rent: SGD {request.rent:,.0f} per month.")

    return AgentOutput(
        agent_name="price_agent",
        summary="Price assessment is running in placeholder mode.",
        risk_level="unknown",
        findings=findings,
        recommendations=["Compare against nearby listings once Part C mock data is populated."],
        data={"rent": request.rent, "bedrooms": request.bedrooms},
    )


def create_price_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="price_agent",
        model=model,
        instruction=(
            "Assess whether the requested rent is reasonable for the area and unit type. "
            "Part C will add listings data tools.\n"
            + INTERNAL_JSON_OUTPUT_INSTRUCTION
        ),
        output_key="price_output",
    )


price_agent = create_price_agent()


__all__ = ["assess_price", "create_price_agent", "price_agent"]
