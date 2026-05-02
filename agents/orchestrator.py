"""ADK root orchestrator: parallel specialist agents, then synthesizer."""

from __future__ import annotations

from typing import Any

from agents import AgentInput, AgentOutput
from agents.contract_agent import assess_contract, create_contract_agent
from agents.intake_agent import IntakeRouterAgent, create_intake_extractor_agent
from agents.location_agent import assess_location, create_location_agent
from agents.price_agent import assess_price, create_price_agent
from agents.risk_agent import assess_risk, create_risk_agent
from agents.synthesizer import create_synthesizer_agent, format_report, synthesize_outputs
from config import settings
from google.adk.agents import ParallelAgent, SequentialAgent


def create_root_agent(
    specialist_model: str = settings.specialist_model,
    synthesizer_model: str = settings.synthesizer_model,
) -> IntakeRouterAgent:
    specialist_team = ParallelAgent(
        name="safenest_parallel_specialists",
        sub_agents=[
            create_location_agent(specialist_model),
            create_contract_agent(specialist_model),
            create_price_agent(specialist_model),
            create_risk_agent(specialist_model),
        ],
    )
    analysis_workflow = SequentialAgent(
        name="safenest_analysis_workflow",
        sub_agents=[specialist_team, create_synthesizer_agent(synthesizer_model)],
    )
    return IntakeRouterAgent(
        name="safenest_root",
        sub_agents=[
            create_intake_extractor_agent(specialist_model),
            analysis_workflow,
        ],
    )


def run_offline_assessment(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    outputs = [
        assess_location(request),
        assess_contract(request),
        assess_price(request),
        assess_risk(request),
    ]
    return synthesize_outputs(outputs)


def run_offline_report(input_data: AgentInput | dict[str, Any]) -> str:
    return format_report(run_offline_assessment(input_data))


root_agent = create_root_agent()


__all__ = [
    "create_root_agent",
    "root_agent",
    "run_offline_assessment",
    "run_offline_report",
]
