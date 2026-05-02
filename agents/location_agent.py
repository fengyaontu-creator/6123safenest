"""Location agent for rental commute and neighbourhood checks."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool


def _load_stations(path: Path = settings.mrt_stations_path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def _match_address_area(address: str, stations: list[dict[str, Any]]) -> dict[str, Any] | None:
    address_norm = address.lower()
    for station in stations:
        aliases = [station.get("name", ""), *station.get("aliases", [])]
        if any(alias.lower() in address_norm for alias in aliases):
            return station
    return None


def nearest_mrt(address: str) -> dict[str, Any]:
    """Return a deterministic MRT estimate from mock station data."""

    stations = _load_stations()
    if not stations:
        return {"found": False, "message": "No MRT station data available."}

    matched = _match_address_area(address, stations) or stations[0]
    distance = float(matched.get("typical_distance_km", 0.8))
    return {
        "found": True,
        "station": matched["name"],
        "line": matched.get("line", "Unknown"),
        "distance_km": round(distance, 2),
        "estimated_walk_min": round(distance / 0.08),
        "matched_area": matched.get("area", matched["name"]),
    }


def commute_estimate(address: str, destination: str = "CBD") -> dict[str, Any]:
    """Estimate transit time to a common destination such as CBD or NTU."""

    stations = _load_stations()
    matched = _match_address_area(address, stations) if stations else None
    if not matched:
        return {
            "destination": destination,
            "estimated_minutes": 45,
            "confidence": "low",
            "note": "Address did not match mock station areas.",
        }

    key = f"commute_to_{destination.lower()}_min"
    minutes = int(matched.get(key, matched.get("commute_to_cbd_min", 40)))
    return {
        "destination": destination,
        "estimated_minutes": minutes,
        "confidence": "medium",
        "from_station": matched["name"],
    }


def assess_location(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    """Run the deterministic location assessment used by tests and CLI."""

    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    mrt = nearest_mrt(request.address)
    cbd = commute_estimate(request.address, "CBD")
    ntu = commute_estimate(request.address, "NTU")

    distance = float(mrt.get("distance_km", 2.0))
    score = max(0.0, min(100.0, 100 - distance * 20 - max(cbd["estimated_minutes"] - 35, 0)))
    risk_level = "low" if score >= 70 else "medium" if score >= 45 else "high"

    findings = [
        f"Nearest MRT: {mrt.get('station', 'unknown')} ({mrt.get('distance_km', 'n/a')} km).",
        f"Estimated commute to CBD: {cbd['estimated_minutes']} minutes.",
        f"Estimated commute to NTU: {ntu['estimated_minutes']} minutes.",
    ]
    recommendations = []
    if distance > 1.0:
        recommendations.append("Ask the landlord for the exact block and verify walking time.")
    if cbd["estimated_minutes"] > 50:
        recommendations.append("Check peak-hour commute before signing.")

    return AgentOutput(
        agent_name="location_agent",
        summary=f"Location risk is {risk_level} for {request.address}.",
        risk_level=risk_level,
        score=round(score, 1),
        findings=findings,
        evidence=[mrt.get("matched_area", request.address), "mock MRT dataset"],
        recommendations=recommendations,
        data={"nearest_mrt": mrt, "commute": {"cbd": cbd, "ntu": ntu}},
    )


LOCATION_AGENT_INSTRUCTION = """
You assess Singapore rental locations. Use the tools to estimate nearest MRT,
commute time to CBD/NTU, and practical location risks.
""" 


def create_location_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="location_agent",
        model=model,
        instruction=LOCATION_AGENT_INSTRUCTION + INTERNAL_JSON_OUTPUT_INSTRUCTION,
        tools=[FunctionTool(nearest_mrt), FunctionTool(commute_estimate)],
        output_key="location_output",
    )


location_agent = create_location_agent()


__all__ = [
    "assess_location",
    "commute_estimate",
    "create_location_agent",
    "location_agent",
    "nearest_mrt",
]
