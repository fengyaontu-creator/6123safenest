"""Shared agent schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "unknown"]


class AgentInput(BaseModel):
    address: str | None = Field(default=None, min_length=1)
    rent: float | None = Field(default=None, ge=0)
    contract_path: str | None = None
    bedrooms: int | None = Field(default=None, ge=0)


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


__all__ = [
    "AgentInput",
    "AgentOutput",
    "INTERNAL_JSON_OUTPUT_INSTRUCTION",
    "RiskLevel",
]
