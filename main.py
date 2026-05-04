"""SafeNest command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import json

from agents import AgentInput
from agents.orchestrator import root_agent
from config import settings
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from dotenv import load_dotenv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a SafeNest rental assessment.")
    parser.add_argument("--address", default=None, help="Rental property address or area.")
    parser.add_argument("--rent", type=float, default=None, help="Monthly rent in SGD.")
    parser.add_argument("--contract", default=None, help="Path to a rental contract PDF.")
    parser.add_argument("--bedrooms", type=int, default=None, help="Number of bedrooms.")
    return parser


def build_user_prompt(request: AgentInput) -> str:
    payload = request.model_dump()
    return (
        "Assess this Singapore rental lead with the SafeNest multi-agent team. "
        "Run the location, contract, price, and risk agents first, then synthesize "
        "the four outputs into a tenant-facing report.\n\n"
        f"Input JSON:\n{json.dumps(payload, indent=2)}"
    )


async def run_with_adk_runner(request: AgentInput) -> str:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=settings.runner_app_name,
        user_id="cli_user",
        state={
            "address": request.address,
            "rent": request.rent,
            "contract_path": request.contract_path,
            "bedrooms": request.bedrooms,
        },
    )
    runner = Runner(
        agent=root_agent,
        app_name=settings.runner_app_name,
        session_service=session_service,
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text=build_user_prompt(request))],
    )

    final_texts: list[str] = []
    async for event in runner.run_async(
        user_id="cli_user",
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts or []:
                if part.text:
                    final_texts.append(part.text)

    latest_session = await session_service.get_session(
        app_name=settings.runner_app_name,
        user_id="cli_user",
        session_id=session.id,
    )
    if latest_session and latest_session.state.get("final_report"):
        return str(latest_session.state["final_report"]).strip()

    if final_texts:
        return final_texts[-1].strip()

    return "ADK Runner completed, but no final report text was returned."


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    request = AgentInput(
        address=args.address,
        rent=args.rent,
        contract_path=args.contract,
        bedrooms=args.bedrooms,
    )
    print(asyncio.run(run_with_adk_runner(request)))


if __name__ == "__main__":
    main()
