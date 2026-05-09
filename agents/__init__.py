"""Shared agent schemas."""

from __future__ import annotations

from typing import Any, Literal

from google.genai import types
from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "unknown"]


class AgentInput(BaseModel):
    address: str | None = Field(default=None, min_length=1)
    rent: float | None = Field(default=None, ge=0)
    contract_path: str | None = None
    contract_text: str | None = None
    contract_file_name: str | None = None
    bedrooms: int | None = Field(default=None, ge=0)
    agent_name: str | None = None
    agent_reg_no: str | None = None


class AgentOutput(BaseModel):
    agent_name: str
    summary: str
    risk_level: RiskLevel = "unknown"
    score: float | None = Field(default=None, ge=0, le=100)
    findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


INTERNAL_JSON_OUTPUT_INSTRUCTION = """
Output is for internal orchestration only, not for the end user.
Return valid JSON only. Do not write a tenant-facing report, greeting, markdown,
or explanatory prose.
The JSON must match AgentOutput with these keys:
agent_name, summary, risk_level, score, findings, evidence, recommendations, data.
Use concise factual values. The synthesizer is the only agent that writes the
user-facing report.
"""


def afc_limiter(maximum_remote_calls: int = 2) -> types.GenerateContentConfig:
    """Limit Gemini automatic function-calling loops for ADK tool agents."""

    return types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=maximum_remote_calls,
        )
    )


__all__ = [
    "AgentInput",
    "AgentOutput",
    "INTERNAL_JSON_OUTPUT_INSTRUCTION",
    "RiskLevel",
    "afc_limiter",
]
