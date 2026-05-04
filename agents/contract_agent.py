"""Contract agent placeholder for the ADK team."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from config import settings
from google.adk.agents import LlmAgent


def assess_contract(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    findings: list[str] = []
    evidence: list[str] = []

    if request.contract_path:
        path = Path(request.contract_path)
        if path.exists():
            findings.append("Contract file is present for later PDF clause extraction.")
            evidence.append(str(path))
        else:
            findings.append("Contract path was provided but the file was not found.")
    else:
        findings.append("No contract file was provided.")

    return AgentOutput(
        agent_name="contract_agent",
        summary="Contract review is running in placeholder mode until Part B tools are connected.",
        risk_level="unknown",
        score=None,
        findings=findings,
        evidence=evidence,
        recommendations=["Complete Part B PDF parsing and RAG checks before relying on contract advice."],
        data={"contract_path": request.contract_path},
    )


def create_contract_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="contract_agent",
        model=model,
        instruction=(
            "Review Singapore rental contracts for unusual clauses, deposits, "
            "termination terms, and tenant obligations. This Part A baseline has no "
            "PDF parsing, file inspection, or code execution tool. Never call run_code "
            "or claim to have read an uploaded PDF. If only an uploaded attachment is "
            "available, record that Part B will add PDF parsing and that contract "
            "text or a usable file path is needed.\n"
            + INTERNAL_JSON_OUTPUT_INSTRUCTION
        ),
        output_key="contract_output",
    )


contract_agent = create_contract_agent()


__all__ = ["assess_contract", "contract_agent", "create_contract_agent"]
