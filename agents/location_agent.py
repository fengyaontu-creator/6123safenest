"""Location agent for rental commute and neighbourhood checks."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION, afc_limiter
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool


DESTINATION_ALIASES = {
    "CBD": "CBD_Raffles_Place",
    "CBD_RAFFLES_PLACE": "CBD_Raffles_Place",
    "RAFFLES_PLACE": "CBD_Raffles_Place",
    "NTU": "NTU",
}

MOCK_CONVENIENCE_STORE_DENSITY = {
    "Jurong West": 8.5,
    "Boon Lay": 8.0,
    "Pioneer": 6.5,
    "Tampines": 9.0,
    "Yishun": 7.0,
    "Woodlands": 7.2,
    "Clementi": 8.2,
    "Ang Mo Kio": 8.8,
    "Serangoon": 8.4,
    "Punggol": 6.8,
}

DEFAULT_CONVENIENCE_STORE_DENSITY = 4.0


def _load_mrt_data(path: Path = settings.mrt_stations_path) -> dict[str, Any]:
    if not path.exists():
        return {"stations": [], "destinations": {}, "metadata": {}}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return {"stations": data, "destinations": {}, "metadata": {}}
    if isinstance(data, dict):
        return {
            "stations": data.get("stations", []),
            "destinations": data.get("destinations", {}),
            "metadata": data.get("metadata", {}),
        }
    return {"stations": [], "destinations": {}, "metadata": {}}


def _load_stations(path: Path = settings.mrt_stations_path) -> list[dict[str, Any]]:
    return _load_mrt_data(path)["stations"]


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
    if not address:
        return None
    address_norm = address.lower()
    for station in stations:
        aliases = [
            station.get("name", ""),
            station.get("station_id", ""),
            *station.get("aliases", []),
            *station.get("nearby_areas", []),
        ]
        if any(alias.lower() in address_norm for alias in aliases):
            return station
    return None


def _station_line_label(station: dict[str, Any]) -> str:
    lines = station.get("lines")
    if isinstance(lines, list) and lines:
        return " / ".join(lines)
    return station.get("line", "Unknown")


def _station_area_label(station: dict[str, Any]) -> str:
    areas = station.get("nearby_areas")
    if isinstance(areas, list) and areas:
        return areas[0]
    return station.get("area", station.get("name", "Unknown"))


def _destination_key(destination: str) -> str:
    normalized = destination.strip().upper().replace(" ", "_")
    return DESTINATION_ALIASES.get(normalized, destination)


def nearest_mrt(address: str) -> dict[str, Any]:
    """Return a deterministic MRT estimate from mock station data."""

    stations = _load_stations()
    if not stations:
        return {"found": False, "message": "No MRT station data available."}

    matched = _match_address_area(address, stations) or stations[0]
    distance = float(matched.get("typical_distance_km", 0.8))
    coords = matched.get("coordinates") or {}
    return {
        "found": True,
        "station_id": matched.get("station_id"),
        "station": matched["name"],
        "line": _station_line_label(matched),
        "distance_km": round(distance, 2),
        "estimated_walk_min": round(distance / 0.08),
        "matched_area": _station_area_label(matched),
        "coordinates": {
            "lat": coords.get("lat"),
            "lng": coords.get("lng"),
        },
        "remarks": matched.get("remarks"),
    }


def commute_estimate(address: str, destination: str = "CBD") -> dict[str, Any]:
    """Estimate transit time to a common destination such as CBD or NTU."""

    mrt_data = _load_mrt_data()
    stations = mrt_data["stations"]
    matched = _match_address_area(address, stations) if stations else None
    if not matched:
        return {
            "destination": destination,
            "estimated_minutes": 45,
            "confidence": "low",
            "note": "Address did not match mock station areas.",
        }

    destination_key = _destination_key(destination)
    commute_minutes = matched.get("commute_minutes", {})
    if destination_key in commute_minutes:
        minutes = int(commute_minutes[destination_key])
    else:
        legacy_key = f"commute_to_{destination.lower()}_min"
        minutes = int(matched.get(legacy_key, matched.get("commute_to_cbd_min", 40)))
    destination_info = mrt_data["destinations"].get(destination_key, {})
    return {
        "destination": destination_key,
        "destination_name": destination_info.get("full_name", destination),
        "estimated_minutes": minutes,
        "confidence": "medium",
        "from_station": matched["name"],
        "from_station_id": matched.get("station_id"),
    }


def _clip_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _convenience_density_for_area(area: str, station_name: str) -> float:
    for label in (area, station_name):
        if label in MOCK_CONVENIENCE_STORE_DENSITY:
            return MOCK_CONVENIENCE_STORE_DENSITY[label]
    return DEFAULT_CONVENIENCE_STORE_DENSITY


def surrounding_amenities(address: str) -> dict[str, Any]:
    """Return mock neighbourhood amenity density and MRT proximity scoring."""

    mrt = nearest_mrt(address)
    area = str(mrt.get("matched_area") or "Unknown")
    station = str(mrt.get("station") or "Unknown")
    distance = float(mrt.get("distance_km", 2.0))
    density = _convenience_density_for_area(area, station)
    mrt_proximity_score = _clip_score(100 - distance * 20)
    convenience_score = _clip_score(density * 10)
    surrounding_score = _clip_score((mrt_proximity_score * 0.55) + (convenience_score * 0.45))

    return {
        "mrt_distance_km": round(distance, 2),
        "mrt_proximity_score": mrt_proximity_score,
        "convenience_store_density_per_km2": density,
        "convenience_store_density_source": "mock_by_nearby_area",
        "convenience_score": convenience_score,
        "surrounding_score": surrounding_score,
    }


def run_location_assessment(address: str) -> dict[str, Any]:
    """Run all location checks in one tool call for the ADK LlmAgent."""

    return {
        "nearest_mrt": nearest_mrt(address),
        "commute_to_cbd": commute_estimate(address, "CBD"),
        "commute_to_ntu": commute_estimate(address, "NTU"),
        "surrounding_amenities": surrounding_amenities(address),
    }


def _commute_score(cbd_minutes: int, ntu_minutes: int, walk_minutes: int) -> float:
    cbd_penalty = max(cbd_minutes - 35, 0) * 1.2
    ntu_penalty = max(ntu_minutes - 20, 0)
    walk_penalty = max(walk_minutes - 10, 0) * 2
    return _clip_score(100 - cbd_penalty - ntu_penalty - walk_penalty)


def _risk_tips(
    mrt: dict[str, Any],
    cbd: dict[str, Any],
    ntu: dict[str, Any],
    amenities: dict[str, Any],
) -> list[str]:
    tips: list[str] = []
    if not mrt.get("found"):
        tips.append("Address did not match mock MRT data; verify the exact block and nearest station.")
    if float(mrt.get("distance_km", 2.0)) > 1.0:
        tips.append("Nearest MRT appears more than 1 km away; check the actual walking route.")
    if int(cbd.get("estimated_minutes", 60)) > 50:
        tips.append("CBD commute may be long during peak hours.")
    if int(ntu.get("estimated_minutes", 60)) > 35:
        tips.append("NTU commute may require extra transfer or bus time.")
    if float(amenities.get("convenience_store_density_per_km2", 0.0)) < 5.0:
        tips.append("Convenience store density is low in the mock data; inspect nearby daily amenities.")
    if not tips:
        tips.append("Verify the exact block, lift access, and peak-hour walking route before signing.")
    return tips


def assess_location(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    """Run the deterministic location assessment used by tests and CLI."""

    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    address = request.address or ""
    mrt = nearest_mrt(address)
    cbd = commute_estimate(address, "CBD")
    ntu = commute_estimate(address, "NTU")
    amenities = surrounding_amenities(address)

    distance = float(mrt.get("distance_km", 2.0))
    commute_score = _commute_score(
        int(cbd["estimated_minutes"]),
        int(ntu["estimated_minutes"]),
        int(mrt.get("estimated_walk_min", 25)),
    )
    surrounding_score = float(amenities["surrounding_score"])
    score = _clip_score((commute_score * 0.6) + (surrounding_score * 0.4))
    risk_level = "low" if score >= 70 else "medium" if score >= 45 else "high"
    risk_tips = _risk_tips(mrt, cbd, ntu, amenities)

    findings = [
        f"Nearest MRT: {mrt.get('station', 'unknown')} ({mrt.get('distance_km', 'n/a')} km).",
        f"Estimated commute to CBD: {cbd['estimated_minutes']} minutes.",
        f"Estimated commute to NTU: {ntu['estimated_minutes']} minutes.",
        f"Commute score: {commute_score}.",
        f"Surrounding score: {surrounding_score}.",
        (
            "Mock convenience store density: "
            f"{amenities['convenience_store_density_per_km2']} stores/km2."
        ),
    ]
    recommendations = list(risk_tips)
    if distance > 1.0:
        recommendations.append("Ask the landlord for the exact block and verify walking time.")
    if cbd["estimated_minutes"] > 50:
        recommendations.append("Check peak-hour commute before signing.")

    return AgentOutput(
        agent_name="location_agent",
        summary=f"Location risk is {risk_level} for {address}.",
        risk_level=risk_level,
        score=round(score, 1),
        findings=findings,
        evidence=[mrt.get("matched_area", address), "mock MRT dataset"],
        recommendations=recommendations,
        data={
            "nearest_mrt": mrt,
            "commute": {"cbd": cbd, "ntu": ntu},
            "commute_score": commute_score,
            "amenities": amenities,
            "surrounding_score": surrounding_score,
            "risk_tips": risk_tips,
        },
    )


LOCATION_AGENT_INSTRUCTION = """
You assess Singapore rental locations.

Call the run_location_assessment tool exactly once with the provided address.
After the tool returns, immediately produce one JSON AgentOutput and stop.
Do not call any tool a second time.
Do not call nearest_mrt, commute_estimate, or surrounding_amenities directly.
If the tool result is incomplete, mark the missing field as "not_available" or
"needs_user_confirmation" in data and stop.
"""


def create_location_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="location_agent",
        model=model,
        instruction=LOCATION_AGENT_INSTRUCTION + INTERNAL_JSON_OUTPUT_INSTRUCTION,
        tools=[FunctionTool(run_location_assessment)],
        generate_content_config=afc_limiter(2),
        output_key="location_output",
    )


location_agent = create_location_agent()


__all__ = [
    "assess_location",
    "commute_estimate",
    "create_location_agent",
    "location_agent",
    "nearest_mrt",
    "run_location_assessment",
    "surrounding_amenities",
]
