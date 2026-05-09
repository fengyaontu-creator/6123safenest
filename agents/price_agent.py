"""Price agent — rental market benchmarking via listings.csv — C.

Two modes:
  1. Deterministic (``assess_price``) — loads listings.csv, filters by area
     and bedroom count, computes market statistics (median, percentiles), and
     derives a reasonableness score for the user's rent.
  2. ADK (``create_price_agent``) — LlmAgent with a ``lookup_market_rents``
     tool that returns comparable listings for the LLM to reason about.

Edge cases handled:
  - CSV not found → degrade to LLM common-sense assessment
  - No area match → expand to all-Singapore data
  - No bedroom match → drop bedroom filter
  - rent is None → skip scoring
"""

from __future__ import annotations

import csv
import logging
import statistics
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Room type mapping
# ---------------------------------------------------------------------------
# Maps an integer bedroom count to the Room_Type values in listings.csv.
# Special case: 0 (studio) and None are handled separately.
BEDROOM_TO_ROOM_TYPE: dict[int, str] = {
    0: "Studio",
    1: "1-Room",
    2: "2-Room",
    3: "3-Room",
    4: "4-Room",
    5: "5-Room",
}

# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def load_listings(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load all listings from the CSV file.

    Returns:
        List of dicts with keys: address, room_type, area_sqm, monthly_rent_sgd,
        listing_date.  Empty list if the file is missing or unreadable.
    """
    csv_path = Path(path) if path else settings.listings_path
    if not csv_path.exists():
        logger.warning("Listings CSV not found: %s", csv_path)
        return []

    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                rows.append({
                    "address": row.get("Address", "").strip(),
                    "room_type": row.get("Room_Type", "").strip(),
                    "area_sqm": float(row.get("Area_sqm", 0)),
                    "monthly_rent_sgd": float(row.get("Monthly_Rent_SGD", 0)),
                    "listing_date": row.get("Listing_Date", "").strip(),
                })
            except (ValueError, TypeError):
                continue
    return rows


def filter_by_area(listings: list[dict[str, Any]], address: str | None) -> list[dict[str, Any]]:
    """Filter listings whose *address* contains the given area string (case-insensitive).

    If *address* is empty or None, returns all listings.
    """
    if not address:
        return listings
    addr_norm = address.lower().split()
    # Match if ANY word from the query address appears in the listing address
    return [
        row for row in listings
        if any(word in row["address"].lower() for word in addr_norm)
    ]


def filter_by_bedrooms(listings: list[dict[str, Any]], bedrooms: int | None) -> list[dict[str, Any]]:
    """Filter listings matching the given bedroom count.

    If *bedrooms* is None, returns all listings.
    """
    if bedrooms is None:
        return listings
    room_type = BEDROOM_TO_ROOM_TYPE.get(bedrooms)
    if not room_type:
        return listings
    return [row for row in listings if row["room_type"] == room_type]


def compute_market_stats(listings: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute rental market statistics from a list of listings.

    Returns:
        Dict with ``count``, ``min``, ``max``, ``mean``, ``median``,
        ``p25``, ``p75``, and ``rents`` (sorted list of all rents).
        Values are None when the listing set is empty.
    """
    if not listings:
        return {
            "count": 0,
            "min": None, "max": None, "mean": None, "median": None,
            "p25": None, "p75": None,
            "rents": [],
        }

    rents = sorted(row["monthly_rent_sgd"] for row in listings)
    n = len(rents)

    def _percentile(sorted_vals: list[float], p: float) -> float:
        """Linear-interpolation percentile (matches numpy default)."""
        k = (len(sorted_vals) - 1) * p / 100.0
        f = int(k)
        c = k - f
        if f + 1 < len(sorted_vals):
            return round(sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f]), 1)
        return round(sorted_vals[f], 1)

    return {
        "count": n,
        "min": rents[0],
        "max": rents[-1],
        "mean": round(statistics.mean(rents), 1),
        "median": _percentile(rents, 50),
        "p25": _percentile(rents, 25),
        "p75": _percentile(rents, 75),
        "rents": rents,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _percentile_rank(sorted_vals: list[float], value: float) -> float:
    """Where does *value* fall in *sorted_vals*?  Returns 0‑100."""
    if not sorted_vals:
        return 50.0
    below = sum(1 for v in sorted_vals if v < value)
    return round(below / len(sorted_vals) * 100, 1)


def _price_score(rent: float, stats: dict[str, Any]) -> dict[str, Any]:
    """Derive a 0‑100 score from where the rent falls in the market.

    Returns:
        ``{"score": float, "position": str, "percentile": float, "advice": str}``
    """
    pct = _percentile_rank(stats["rents"], rent)

    if stats["count"] == 0:
        return {"score": 50.0, "position": "unknown", "percentile": pct,
                "advice": "No comparable listings available for benchmarking."}

    p25 = stats["p25"] or 0
    p75 = stats["p75"] or 0

    if pct <= 10:
        return {"score": 30.0, "position": "very_low", "percentile": pct,
                "advice": "Rent is unusually low. Verify the listing is not a scam (too-good-to-be-true pricing)."}
    elif pct <= 25:
        return {"score": 70.0, "position": "below_market", "percentile": pct,
                "advice": "Rent is below market average — good value if the unit condition is acceptable."}
    elif pct <= 75:
        return {"score": 90.0, "position": "market_rate", "percentile": pct,
                "advice": "Rent is within the typical market range."}
    elif pct <= 90:
        return {"score": 50.0, "position": "above_market", "percentile": pct,
                "advice": f"Rent is above the market median (median=SGD {stats['median']}). "
                         f"Consider negotiating towards SGD {stats['p50'] or stats['median']}."}
    else:
        return {"score": 30.0, "position": "very_high", "percentile": pct,
                "advice": f"Rent is significantly above market (max comparable=SGD {stats['max']}). "
                         f"Strongly consider negotiating or looking at other units."}


# ---------------------------------------------------------------------------
# Deterministic assess_price
# ---------------------------------------------------------------------------


def assess_price(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    """Run deterministic price assessment (CLI / tests)."""
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)

    findings: list[str] = []
    recommendations: list[str] = []
    data: dict[str, Any] = {"rent": request.rent, "bedrooms": request.bedrooms}

    # No rent provided
    if request.rent is None:
        return AgentOutput(
            agent_name="price_agent",
            summary="No rent amount was provided for price assessment.",
            risk_level="unknown",
            score=None,
            findings=["Rent amount is missing — cannot benchmark."],
            recommendations=["Provide the monthly rent in SGD to receive market comparison."],
            data=data,
        )

    # Load data
    all_listings = load_listings()
    if not all_listings:
        return AgentOutput(
            agent_name="price_agent",
            summary="Market data is unavailable for price comparison.",
            risk_level="unknown",
            score=50.0,
            findings=["Rental listings CSV is missing or empty — cannot benchmark."],
            recommendations=[
                f"Manually check recent listings for {request.address or 'Singapore'} on PropertyGuru or 99.co."
            ],
            data={"rent": request.rent, "listings_available": False},
        )

    # Filter
    by_area = filter_by_area(all_listings, request.address)
    by_bedrooms = filter_by_bedrooms(by_area, request.bedrooms)

    # Progressive relaxation
    if len(by_bedrooms) < 3 and request.bedrooms is not None:
        findings.append(
            f"Only {len(by_bedrooms)} listing(s) match {request.bedrooms}-bedroom in the area. "
            "Expanding to all bedroom types in the same area."
        )
        by_bedrooms = by_area

    if len(by_bedrooms) < 3:
        findings.append(
            f"Only {len(by_bedrooms)} listing(s) match the area '{request.address}'. "
            "Expanding to all-Singapore data."
        )
        by_bedrooms = all_listings

    # Stats
    stats = compute_market_stats(by_bedrooms)
    scoring = _price_score(request.rent, stats)

    # Risk level from score
    score = scoring["score"]
    if score >= 70:
        risk_level = "low"
    elif score >= 45:
        risk_level = "medium"
    else:
        risk_level = "high"

    # Build output
    findings.extend([
        f"Comparable listings found: {stats['count']}",
        f"Market median: SGD {stats['median']}/month",
        f"Market range (p25–p75): SGD {stats['p25']} – SGD {stats['p75']}/month",
        f"Your rent (SGD {request.rent:,.0f}) is at the {scoring['percentile']}th percentile — {scoring['position']}.",
    ])

    recommendations.append(scoring["advice"])
    if scoring["position"] in ("above_market", "very_high"):
        recommendations.append(
            "Consider using the market data above to negotiate a lower rent with the landlord."
        )

    data.update({
        "market_stats": {k: v for k, v in stats.items() if k != "rents"},
        "scoring": scoring,
        "filter_stages": {
            "all": len(all_listings),
            "by_area": len(by_area),
            "final": len(by_bedrooms),
        },
    })

    return AgentOutput(
        agent_name="price_agent",
        summary=f"Rent is {scoring['position']} (score={score}/100, risk={risk_level}).",
        risk_level=risk_level,
        score=score,
        findings=findings,
        evidence=[f"Source: {settings.listings_path}"],
        recommendations=recommendations,
        data=data,
    )


# ---------------------------------------------------------------------------
# ADK tool & agent
# ---------------------------------------------------------------------------


def lookup_market_rents(address: str, bedrooms: int | None = None) -> dict[str, Any]:
    """Look up comparable rental listings for an area and bedroom count.

    Args:
        address: Area or street name to search (e.g. "Jurong West").
        bedrooms: Number of bedrooms (2 = 2-Room, etc.).  Pass null to include all.

    Returns:
        Market statistics and a sample of comparable listings.
    """
    all_listings = load_listings()
    by_area = filter_by_area(all_listings, address)
    by_bedrooms = filter_by_bedrooms(by_area, bedrooms)

    if len(by_bedrooms) < 3 and bedrooms is not None:
        by_bedrooms = by_area
    if len(by_bedrooms) < 3:
        by_bedrooms = all_listings

    stats = compute_market_stats(by_bedrooms)
    return {
        "count": stats["count"],
        "median": stats["median"],
        "p25": stats["p25"],
        "p75": stats["p75"],
        "min": stats["min"],
        "max": stats["max"],
        "mean": stats["mean"],
        "sample_listings": [
            {
                "address": row["address"],
                "room_type": row["room_type"],
                "monthly_rent_sgd": row["monthly_rent_sgd"],
                "area_sqm": row["area_sqm"],
            }
            for row in by_bedrooms[:5]
        ],
    }


def create_price_agent(model: str = settings.specialist_model) -> LlmAgent:
    """构建 Price Agent 的 LLM 实例。"""
    return LlmAgent(
        name="price_agent",
        model=model,
        instruction=(
            "Assess whether the requested rent is reasonable for the area and "
            "bedroom count.  Use the `lookup_market_rents` tool to get comparable "
            "listings.\n\n"
            "**Workflow**\n"
            "1. Call `lookup_market_rents` with the user's address and bedroom count.\n"
            "2. Compare the user's rent against the market median, p25, and p75.\n"
            "3. If the rent is above p75, flag it as potentially overpriced.\n"
            "4. If the rent is below p25, flag it as suspiciously cheap.\n"
            "5. Provide a score (0‑100) and actionable negotiation advice.\n\n"
            "User address: {address?}\n"
            "User rent: {rent?}\n"
            "User bedrooms: {bedrooms?}\n"
            + INTERNAL_JSON_OUTPUT_INSTRUCTION
        ),
        tools=[FunctionTool(lookup_market_rents)],
        output_key="price_output",
    )


price_agent = create_price_agent()


__all__ = [
    "assess_price",
    "compute_market_stats",
    "create_price_agent",
    "filter_by_area",
    "filter_by_bedrooms",
    "load_listings",
    "lookup_market_rents",
    "price_agent",
]

