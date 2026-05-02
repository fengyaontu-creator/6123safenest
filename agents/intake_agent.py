"""Intake gate for SafeNest workflow routing."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
import re
from typing import Any

from config import settings
from google.adk.agents import LlmAgent
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import Field


REQUIRED_FIELDS = {
    "address": "rental address",
    "rent": "monthly rent",
    "contract_path": "contract PDF path",
}

INTAKE_EXTRACTION_KEY = "intake_extraction"

FIELD_QUESTIONS = {
    "address": "What is the rental property's full address or nearest block/street?",
    "rent": "What is the monthly rent in SGD?",
    "contract_path": "Please provide the rental contract PDF path, for example data/sample_contract.pdf.",
}


def _content_text(ctx: InvocationContext) -> str:
    if not ctx.user_content or not ctx.user_content.parts:
        return ""
    return "\n".join(part.text or "" for part in ctx.user_content.parts)


def extract_rental_info_from_query(query: str) -> dict[str, Any]:
    """Rule-based fallback extraction for core rental fields."""

    extracted: dict[str, Any] = {}

    json_match = re.search(r"\{.*\}", query, flags=re.DOTALL)
    if json_match:
        try:
            payload = json.loads(json_match.group(0))
            for key in ("address", "rent", "contract_path", "bedrooms"):
                if payload.get(key) not in (None, ""):
                    extracted[key] = payload[key]
        except json.JSONDecodeError:
            pass

    rent_match = re.search(
        r"(?:rent|monthly rent|sgd|s\$|\$)\s*[:=]?\s*([0-9][0-9,]*(?:\.\d+)?)",
        query,
        flags=re.IGNORECASE,
    )
    if rent_match and "rent" not in extracted:
        extracted["rent"] = float(rent_match.group(1).replace(",", ""))

    contract_match = re.search(r"([\w./\\-]+\.pdf)\b", query, flags=re.IGNORECASE)
    if contract_match and "contract_path" not in extracted:
        extracted["contract_path"] = contract_match.group(1)

    bedroom_match = re.search(
        r"\b([0-9]+)\s*(?:bed|beds|bedroom|bedrooms|br)\b",
        query,
        flags=re.IGNORECASE,
    )
    if bedroom_match and "bedrooms" not in extracted:
        extracted["bedrooms"] = int(bedroom_match.group(1))

    address_patterns = [
        r"(?:address|at|located at|property at)\s+['\"]?([^'\"\n,]+(?:\s+[^'\"\n,]+){0,6})",
        r"\b([0-9]{1,4}\s+[A-Za-z][A-Za-z0-9 ]{2,40})\b",
    ]
    for pattern in address_patterns:
        address_match = re.search(pattern, query, flags=re.IGNORECASE)
        if address_match and "address" not in extracted:
            address = address_match.group(1).strip()
            address = re.split(
                r"\s+(?:rent|monthly rent|contract|pdf|for|with|at\s+rent)\b",
                address,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()
            if address and not address.lower().endswith(".pdf"):
                extracted["address"] = address
                break

    return extracted


def parse_model_extraction(value: Any) -> dict[str, Any]:
    """Parse the intake extractor LLM output into normalized fields."""

    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        text = value.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        json_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if json_match:
            text = json_match.group(0)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
    else:
        return {}

    normalized: dict[str, Any] = {}
    for key in ("address", "contract_path"):
        value = payload.get(key)
        if value not in (None, ""):
            normalized[key] = str(value).strip()

    for key in ("rent", "bedrooms"):
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            normalized[key] = float(value) if key == "rent" else int(value)
        except (TypeError, ValueError):
            continue

    return normalized


def create_intake_extractor_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="intake_extractor",
        model=model,
        instruction=(
            "Extract rental analysis intake information from the user's latest request. "
            "Use semantic understanding, not brittle keyword matching. Return JSON only "
            "with these keys: address, rent, contract_path, bedrooms. Use null for any "
            "unknown value. Do not analyze the rental. Do not call run_code, inspect "
            "files, parse PDFs, or use tools. If the user uploaded a PDF but did not "
            "provide a usable path, set contract_path to null."
        ),
        output_key=INTAKE_EXTRACTION_KEY,
    )


def missing_required_fields(data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_FIELDS:
        value = data.get(key)
        if value is None or value == "":
            missing.append(key)
    return missing


def build_missing_info_question(missing: list[str]) -> str:
    questions = [FIELD_QUESTIONS[key] for key in missing]
    if len(questions) == 1:
        return (
            "I need one more detail before running the rental analysis. "
            f"{questions[0]}"
        )

    question_lines = "\n".join(f"- {question}" for question in questions)
    return (
        "I need a few details before running the rental analysis:\n"
        f"{question_lines}"
    )


class IntakeRouterAgent(BaseAgent):
    """Runs analysis only after required intake fields are present."""

    required_fields: dict[str, str] = Field(default_factory=lambda: REQUIRED_FIELDS.copy())

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        state = dict(ctx.session.state)

        if self.sub_agents and self.sub_agents[0].name == "intake_extractor":
            async for event in self.sub_agents[0].run_async(ctx):
                yield event

        model_extracted = parse_model_extraction(
            ctx.session.state.get(INTAKE_EXTRACTION_KEY)
        )
        fallback_extracted = extract_rental_info_from_query(_content_text(ctx))
        extracted = {**fallback_extracted, **model_extracted}
        extracted = {
            key: value for key, value in extracted.items() if state.get(key) in (None, "")
        }

        if extracted:
            ctx.session.state.update(extracted)
            state.update(extracted)

        missing = missing_required_fields(state)

        if missing:
            ctx.end_invocation = True
            yield Event(
                author=self.name,
                invocation_id=ctx.invocation_id,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=build_missing_info_question(missing))],
                ),
                actions=EventActions(
                    state_delta={
                        **extracted,
                        "intake_status": "incomplete",
                        "missing_fields": missing,
                    },
                    end_of_agent=True,
                ),
            )
            return

        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(
                role="model",
                parts=[types.Part(text="Intake complete. Starting specialist analysis.")],
            ),
            actions=EventActions(
                state_delta={
                    **extracted,
                    "intake_status": "complete",
                    "missing_fields": [],
                }
            ),
        )

        for sub_agent in self.sub_agents:
            if sub_agent.name == "intake_extractor":
                continue
            async for event in sub_agent.run_async(ctx):
                yield event


__all__ = [
    "IntakeRouterAgent",
    "build_missing_info_question",
    "create_intake_extractor_agent",
    "extract_rental_info_from_query",
    "FIELD_QUESTIONS",
    "INTAKE_EXTRACTION_KEY",
    "missing_required_fields",
    "parse_model_extraction",
]
