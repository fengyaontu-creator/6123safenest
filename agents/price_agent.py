"""Price agent — 评估月租是否合理,基于 listings.csv 中的同区房源。

作者: C
模仿 location_agent.py 的结构,严格遵守 AgentInput/AgentOutput schema。
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION, afc_limiter
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool


# ===== 常量配置 =====

# 已知的新加坡区域名(按长度倒序排列,优先匹配长名,例如 "Jurong West" 优先于 "Jurong")
KNOWN_SG_AREAS = sorted(
    [
        "Jurong West", "Jurong East", "Boon Lay", "Bukit Batok",
        "Choa Chu Kang", "Woodlands", "Yishun", "Sembawang",
        "Tampines", "Pasir Ris", "Sengkang", "Hougang",
        "Bishan", "Toa Payoh", "Ang Mo Kio", "Clementi",
    ],
    key=len,
    reverse=True,
)


# ===== 私有辅助函数(下划线开头) =====

def _load_listings(path: Path = settings.listings_path) -> list[dict[str, Any]]:
    """从 listings.csv 读取所有房源,返回字典列表。

    把数字字段(月租、面积)转成 float 便于后续计算。
    """
    if not path.exists():
        return []
    listings: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                row["Monthly_Rent_SGD"] = float(row.get("Monthly_Rent_SGD", 0) or 0)
                row["Area_sqm"] = float(row.get("Area_sqm", 0) or 0)
            except (ValueError, TypeError):
                continue  # 跳过坏数据
            listings.append(row)
    return listings


def _extract_area(address: str) -> str:
    """从地址中提取区域名。

    例如 'Block 123 Jurong West St 13' → 'Jurong West'。
    匹配不到返回空字符串。
    """
    if not address:
        return ""
    address_lower = address.lower()
    for area in KNOWN_SG_AREAS:
        if area.lower() in address_lower:
            return area
    return ""


def _bedrooms_to_room_type(bedrooms: int | None) -> str:
    """把 bedrooms 数量映射到 listings.csv 里的 Room_Type 标签。

    简化策略:bedrooms=3 → '3-Room'。匹配不到返回空字符串(不筛选)。
    """
    if bedrooms is None:
        return ""
    target = f"{bedrooms}-Room"
    if target in {"2-Room", "3-Room", "4-Room", "5-Room"}:
        return target
    return ""


# ===== 工具函数(LLM agent 会调用这些) =====

def lookup_comparable_listings(address: str, room_type: str = "") -> dict[str, Any]:
    """查找同区(及可选户型)的可比房源。

    Args:
        address: 完整地址,例如 'Block 123 Jurong West St 13'。
        room_type: 可选户型筛选,例如 '3-Room'。空字符串表示不筛选。

    Returns:
        含 area, count, comparables 的字典。
    """
    listings = _load_listings()
    if not listings:
        return {
            "found": False,
            "message": "Listings dataset is unavailable.",
            "comparables": [],
        }

    area = _extract_area(address)
    if not area:
        return {
            "found": False,
            "message": f"Could not parse a known SG area from address: {address}",
            "comparables": [],
        }

    matched = [
        r for r in listings
        if area.lower() in str(r.get("Address", "")).lower()
    ]
    if room_type:
        matched = [r for r in matched if r.get("Room_Type") == room_type]

    return {
        "found": True,
        "area": area,
        "room_type_filter": room_type or "any",
        "count": len(matched),
        "comparables": [
            {
                "address": r.get("Address"),
                "room_type": r.get("Room_Type"),
                "area_sqm": r.get("Area_sqm"),
                "monthly_rent": r.get("Monthly_Rent_SGD"),
                "listing_date": r.get("Listing_Date"),
            }
            for r in matched
        ],
    }


def compute_price_statistics(address: str, room_type: str = "") -> dict[str, Any]:
    """计算同区(及可选户型)房源的租金统计量。

    Returns:
        含 sample_size / min / max / median / mean / p25 / p75 的字典。
    """
    result = lookup_comparable_listings(address, room_type)
    if not result.get("found") or result.get("count", 0) == 0:
        return {
            "found": False,
            "area": result.get("area", ""),
            "sample_size": 0,
            "message": result.get("message", "No comparable listings found."),
        }

    rents = sorted(c["monthly_rent"] for c in result["comparables"])
    n = len(rents)
    p25_idx = max(0, n // 4)
    p75_idx = min(n - 1, (3 * n) // 4)

    return {
        "found": True,
        "area": result["area"],
        "room_type_filter": result["room_type_filter"],
        "sample_size": n,
        "min": min(rents),
        "max": max(rents),
        "median": float(statistics.median(rents)),
        "mean": round(statistics.mean(rents), 2),
        "p25": float(rents[p25_idx]),
        "p75": float(rents[p75_idx]),
    }


def evaluate_rent_reasonableness(
    rent: float,
    address: str,
    room_type: str = "",
) -> dict[str, Any]:
    """评估给定月租在同区是否合理,并给出议价建议。

    Returns:
        含 verdict / score / suggestion / stats 的字典。
    """
    stats = compute_price_statistics(address, room_type)
    if not stats.get("found"):
        return {
            "verdict": "unknown",
            "score": None,
            "message": stats.get("message", "Insufficient data."),
            "stats": stats,
        }

    median = stats["median"]
    p25 = stats["p25"]
    p75 = stats["p75"]
    diff_pct = round(((rent - median) / median) * 100, 1)

    # 评分逻辑:rent 越低于市场分越高
    if rent <= p25:
        verdict, score = "excellent_deal", 90.0
    elif rent <= median:
        verdict, score = "good_deal", 75.0
    elif rent <= p75:
        verdict, score = "fair_price", 55.0
    else:
        verdict, score = "overpriced", 30.0

    # 极端情况微调
    if rent < p25 * 0.85:
        score = 95.0
    elif rent > p75 * 1.15:
        score = 15.0

    # 议价建议
    if rent > median:
        suggestion = f"Counter-offer at SGD {round(median):,} (area median)."
    elif rent > p25:
        suggestion = f"Try negotiating to SGD {round(p25):,} (25th percentile)."
    else:
        suggestion = "Rent is already below market 25th percentile; minimal negotiation room."

    return {
        "verdict": verdict,
        "score": score,
        "rent_input": rent,
        "median": median,
        "diff_from_median_pct": diff_pct,
        "suggestion": suggestion,
        "stats": stats,
    }


# ===== 主入口:确定性评估(测试 / CLI 用这个) =====

def run_price_assessment(
    rent: float,
    address: str,
    bedrooms: int | None = None,
) -> dict[str, Any]:
    """Run all price checks in one ADK tool call."""

    room_type = _bedrooms_to_room_type(bedrooms)
    return {
        "rent": rent,
        "address": address,
        "bedrooms": bedrooms,
        "room_type": room_type,
        "comparables": lookup_comparable_listings(address, room_type),
        "statistics": compute_price_statistics(address, room_type),
        "evaluation": evaluate_rent_reasonableness(rent, address, room_type),
    }


def assess_price(input_data: AgentInput | dict[str, Any]) -> AgentOutput:
    """运行确定性的租金合理性评估。

    供 tests/test_price.py 和 main.py CLI 直接调用,不经过 LLM。
    严格按 AgentOutput schema 返回。
    """
    request = (
        input_data
        if isinstance(input_data, AgentInput)
        else AgentInput(**input_data)
    )

    address = request.address or ""
    rent = request.rent
    bedrooms = request.bedrooms
    room_type = _bedrooms_to_room_type(bedrooms)

    # ---- 输入缺失:优雅返回 ----
    if not address or rent is None:
        return AgentOutput(
            agent_name="price_agent",
            summary="Price assessment requires both an address and a rent value.",
            risk_level="unknown",
            findings=["Missing address or rent input."],
            recommendations=["Provide --address and --rent to the CLI."],
            data={"rent": rent, "address": address, "bedrooms": bedrooms},
        )

    eval_result = evaluate_rent_reasonableness(rent, address, room_type)

    # ---- 找不到可比数据:返回 unknown ----
    if eval_result["score"] is None:
        return AgentOutput(
            agent_name="price_agent",
            summary=f"No comparable listings for {address}; cannot benchmark rent.",
            risk_level="unknown",
            findings=[
                f"Input rent: SGD {rent:,.0f}.",
                f"Address: {address}.",
                eval_result.get("message", ""),
            ],
            recommendations=[
                "Add more listings to data/listings.csv or broaden the search area.",
            ],
            data={
                "rent": rent,
                "address": address,
                "bedrooms": bedrooms,
                "evaluation": eval_result,
            },
        )

    # ---- 正常评估 ----
    stats = eval_result["stats"]
    score = float(eval_result["score"])
    risk_level: Any = (
        "low" if score >= 70 else "medium" if score >= 45 else "high"
    )

    findings = [
        f"Input rent: SGD {rent:,.0f} per month.",
        f"Area: {stats['area']} ({stats['sample_size']} comparable listings).",
        f"Area median rent: SGD {stats['median']:,.0f}.",
        f"Area rent range: SGD {stats['min']:,.0f} – SGD {stats['max']:,.0f}.",
        (
            f"Verdict: {eval_result['verdict']} "
            f"({eval_result['diff_from_median_pct']:+.1f}% vs median)."
        ),
    ]

    recommendations = [eval_result["suggestion"]]
    if stats["sample_size"] < 5:
        recommendations.append(
            f"Sample size is small ({stats['sample_size']} listings); "
            "treat the benchmark cautiously."
        )

    return AgentOutput(
        agent_name="price_agent",
        summary=(
            f"Rent SGD {rent:,.0f} is {eval_result['diff_from_median_pct']:+.1f}% "
            f"vs {stats['area']} median (verdict: {eval_result['verdict']})."
        ),
        risk_level=risk_level,
        score=round(score, 1),
        findings=findings,
        evidence=[
            f"listings.csv ({stats['sample_size']} entries in {stats['area']})",
        ],
        recommendations=recommendations,
        data={
            "rent": rent,
            "address": address,
            "bedrooms": bedrooms,
            "evaluation": eval_result,
        },
    )


# ===== LLM Agent 定义(Google ADK) =====

PRICE_AGENT_INSTRUCTION = """
You assess whether a requested monthly rent is reasonable for the address and
unit type provided.

Call the run_price_assessment tool once with rent, address, and bedrooms from
session state. The tool performs comparable lookup, price statistics, and rent
reasonableness evaluation in one call.
After the tool returns, produce one JSON AgentOutput and stop.
Do not call any tool a second time.
Always cite the area and sample size in your findings when available.
"""


def create_price_agent(model: str = settings.specialist_model) -> LlmAgent:
    """构建 Price Agent 的 LLM 实例。"""
    return LlmAgent(
        name="price_agent",
        model=model,
        instruction=PRICE_AGENT_INSTRUCTION + INTERNAL_JSON_OUTPUT_INSTRUCTION,
        tools=[FunctionTool(run_price_assessment)],
        generate_content_config=afc_limiter(2),
        output_key="price_output",
    )


price_agent = create_price_agent()


__all__ = [
    "assess_price",
    "compute_price_statistics",
    "create_price_agent",
    "evaluate_rent_reasonableness",
    "lookup_comparable_listings",
    "price_agent",
    "run_price_assessment",
]
