"""Tests for the price agent."""
from __future__ import annotations

from agents import AgentInput
from agents.price_agent import (
    assess_price,
    compute_price_statistics,
    evaluate_rent_reasonableness,
    lookup_comparable_listings,
)


# ===== 工具函数测试 =====

def test_lookup_comparable_listings_jurong_west():
    """从 Jurong West 地址应能找到至少一条同区房源。"""
    result = lookup_comparable_listings("Block 123 Jurong West St 13")
    assert result["found"] is True
    assert result["area"] == "Jurong West"
    assert result["count"] > 0
    assert all("Jurong West" in c["address"] for c in result["comparables"])


def test_compute_price_statistics_jurong_west():
    """Jurong West 应能算出租金统计量。"""
    stats = compute_price_statistics("Jurong West")
    assert stats["found"] is True
    assert stats["sample_size"] > 0
    assert stats["min"] <= stats["median"] <= stats["max"]
    assert stats["median"] > 0


def test_evaluate_rent_reasonableness_below_median():
    """低于中位数的租金应给出 good_deal 或 excellent_deal 评级。"""
    result = evaluate_rent_reasonableness(2000, "Block 123 Jurong West St 13")
    assert result["verdict"] in ("good_deal", "excellent_deal")
    assert result["score"] >= 70


# ===== Agent 主函数测试 =====

def test_assess_price_returns_valid_output():
    """演示用例:Jurong West $2000 应返回合理输出。"""
    output = assess_price(
        AgentInput(address="Block 123 Jurong West St 13", rent=2000)
    )
    assert output.agent_name == "price_agent"
    assert output.score is not None
    assert output.score >= 70
    assert output.risk_level in ("low", "medium")
    assert len(output.findings) > 0
    assert len(output.recommendations) > 0


def test_assess_price_handles_missing_input():
    """没填地址或租金应优雅处理。"""
    output = assess_price(AgentInput(address=None, rent=None))
    assert output.agent_name == "price_agent"
    assert output.risk_level == "unknown"


def test_assess_price_above_median_returns_lower_score():
    """高于中位数的租金应得到较低评分。"""
    output = assess_price(AgentInput(address="Jurong West Ave 5", rent=3500))
    assert output.score is not None
    assert output.score < 70
