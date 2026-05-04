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
    data: dict[str, Any] = {
        "contract_path": request.contract_path,
        "contract_file_name": request.contract_file_name,
        "contract_text_available": bool(request.contract_text),
    }

    if request.contract_text:
        findings.append("Uploaded contract text is available for clause review.")
        evidence.append(request.contract_file_name or "uploaded contract file")
        data["contract_text_preview"] = request.contract_text[:500]
    elif request.contract_path:
        path = Path(request.contract_path)
        if path.exists():
            findings.append("Contract file is present for later PDF clause extraction.")
            evidence.append(str(path))
        else:
            findings.append("Contract path was provided but the file was not found.")
    elif request.contract_file_name:
        findings.append("Contract file was uploaded, but text extraction was unavailable.")
        evidence.append(request.contract_file_name)
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
        data=data,
    )


def create_contract_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="contract_agent",
        model=model,
        instruction=(
            "Review Singapore rental contracts for unusual clauses, deposits, "
            "termination terms, and tenant obligations. Use contract_text from ADK "
            "session state when it is available from a Web upload, or contract_path "
            "when the CLI provided a path. Never call run_code or inspect files "
            "yourself.\n"
            "Uploaded contract file name: {contract_file_name?}\n"
            "Extracted uploaded contract text: {contract_text?}\n"
            + INTERNAL_JSON_OUTPUT_INSTRUCTION
        ),
        output_key="contract_output",
    )


contract_agent = create_contract_agent()


__all__ = ["assess_contract", "contract_agent", "create_contract_agent"]
