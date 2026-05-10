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
from guardrails import check_injection, check_scope, redact_pii
from pydantic import Field


REQUIRED_FIELDS = {
    "address": "rental address",
    "rent": "monthly rent",
    "contract_path": "contract PDF",
}

INTAKE_EXTRACTION_KEY = "intake_extraction"

FIELD_QUESTIONS = {
    "address": "What is the rental property's full address or nearest block/street?",
    "rent": "What is the monthly rent in SGD?",
    "contract_path": "Please provide the rental contract PDF path, for example data/sample_contract.pdf.",
}

WEB_FIELD_QUESTIONS = {
    **FIELD_QUESTIONS,
    "contract_path": "Please upload the rental contract PDF file.",
}


def _content_text(ctx: InvocationContext) -> str:
    if not ctx.user_content or not ctx.user_content.parts:
        return ""
    return "\n".join(part.text or "" for part in ctx.user_content.parts)


def _apply_event_state(ctx: InvocationContext, event: Event) -> None:
    if event.actions and event.actions.state_delta:
        ctx.session.state.update(event.actions.state_delta)


def _clear_visible_actions(event: Event) -> Event:
    event.actions.state_delta = {}
    event.actions.transfer_to_agent = None
    return event


def _is_visible_final_report(event: Event) -> bool:
    if event.author != "synthesizer" or not event.is_final_response():
        return False
    if not event.content or not event.content.parts:
        return False
    return any(part.text for part in event.content.parts)


def _analysis_fallback_report(state: dict[str, Any], error: Exception) -> str:
    from agents import AgentInput
    from agents.contract_agent import assess_contract
    from agents.location_agent import assess_location
    from agents.price_agent import assess_price
    from agents.risk_agent import assess_risk
    from agents.synthesizer import format_report, synthesize_outputs

    request = AgentInput(
        address=state.get("address"),
        rent=state.get("rent"),
        contract_path=state.get("contract_path"),
        contract_text=state.get("contract_text"),
        contract_file_name=state.get("contract_file_name"),
        bedrooms=state.get("bedrooms"),
        agent_name=state.get("agent_name"),
        agent_reg_no=state.get("agent_reg_no"),
    )
    output = synthesize_outputs(
        [
            assess_location(request),
            assess_contract(request),
            assess_price(request),
            assess_risk(
                request,
                agent_name=request.agent_name,
                agent_reg_no=request.agent_reg_no,
            ),
        ]
    )
    report = format_report(output)
    return (
        f"{report}\n\n"
        "Note: The live Gemini specialist run was temporarily unavailable, "
        f"so this report used the deterministic fallback. Error: {type(error).__name__}."
    )


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
    for key in ("address", "contract_path", "agent_name", "agent_reg_no"):
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
            "with these keys: address, rent, contract_path, bedrooms, agent_name, "
            "agent_reg_no. Use null for any unknown value.\n\n"
            "For agent_name: look for names near 'agent', 'salesperson', '中介', "
            "or CEA registration numbers (RxxxxxxX format). "
            "For agent_reg_no: look for CEA registration numbers (e.g. R123456A, P015022G).\n\n"
            "Do not analyze the rental. Do not call run_code, inspect "
            "files, parse PDFs, or use tools. If the user uploaded a PDF but did not "
            "provide a usable path, set contract_path to null."
        ),
        output_key=INTAKE_EXTRACTION_KEY,
    )


def has_contract_information(data: dict[str, Any]) -> bool:
    return any(
        data.get(key)
        for key in (
            "contract_path",
            "contract_text",
            "contract_file_uploaded",
            "contract_file_name",
        )
    )


def missing_required_fields(data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_FIELDS:
        if key == "contract_path" and has_contract_information(data):
            continue
        value = data.get(key)
        if value is None or value == "":
            missing.append(key)
    return missing


def build_missing_info_question(missing: list[str], interface: str | None = None) -> str:
    field_questions = WEB_FIELD_QUESTIONS if interface == "web" else FIELD_QUESTIONS
    questions = [field_questions[key] for key in missing]
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
        user_text = _content_text(ctx)
        if user_text.strip():
            injection_hit = check_injection(user_text)
            if injection_hit:
                ctx.end_invocation = True
                ctx.session.state["guardrail_block"] = {
                    "layer": "injection_filter",
                    "category": injection_hit["category"],
                }
                yield Event(
                    author=self.name,
                    invocation_id=ctx.invocation_id,
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text=injection_hit["message"])],
                    ),
                    actions=EventActions(end_of_agent=True),
                )
                return

            scope_hit = check_scope(user_text)
            if scope_hit:
                ctx.end_invocation = True
                ctx.session.state["guardrail_block"] = {
                    "layer": "scope_guard",
                    "category": scope_hit["category"],
                }
                yield Event(
                    author=self.name,
                    invocation_id=ctx.invocation_id,
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text=scope_hit["message"])],
                    ),
                    actions=EventActions(end_of_agent=True),
                )
                return

            ctx.session.state["user_query_redacted"] = redact_pii(user_text)

        state = dict(ctx.session.state)

        if self.sub_agents and self.sub_agents[0].name == "intake_extractor":
            async for event in self.sub_agents[0].run_async(ctx):
                _apply_event_state(ctx, event)

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
                    parts=[
                        types.Part(
                            text=build_missing_info_question(
                                missing,
                                str(state.get("interface") or ""),
                            )
                        )
                    ],
                ),
                actions=EventActions(end_of_agent=True),
            )
            ctx.session.state.update(
                {
                    **extracted,
                    "intake_status": "incomplete",
                    "missing_fields": missing,
                }
            )
            return

        ctx.session.state.update(
            {
                **extracted,
                "intake_status": "complete",
                "missing_fields": [],
            }
        )

        for sub_agent in self.sub_agents:
            if sub_agent.name == "intake_extractor":
                continue
            try:
                async for event in sub_agent.run_async(ctx):
                    _apply_event_state(ctx, event)
                    if _is_visible_final_report(event):
                        yield _clear_visible_actions(event)
            except Exception as error:
                ctx.end_invocation = True
                yield Event(
                    author="synthesizer",
                    invocation_id=ctx.invocation_id,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=_analysis_fallback_report(ctx.session.state, error)
                            )
                        ],
                    ),
                    actions=EventActions(end_of_agent=True),
                )
                return


__all__ = [
    "IntakeRouterAgent",
    "build_missing_info_question",
    "create_intake_extractor_agent",
    "extract_rental_info_from_query",
    "FIELD_QUESTIONS",
    "has_contract_information",
    "INTAKE_EXTRACTION_KEY",
    "missing_required_fields",
    "parse_model_extraction",
]
