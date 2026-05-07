"""Risk agent tests — D.

Covers:
  - Local CSV lookup (name / reg_no / not-found)
  - Combined verification (API + CSV fallback)
  - Deterministic assess_risk (named agent / reg_no / no agent / empty input)
  - AgentOutput schema compliance
  - Risk scoring and risk-level thresholds
  - Agent-name extraction from contract text
"""

import pytest

from agents import AgentInput, AgentOutput
from agents.risk_agent import (
    _extract_agent_name_from_text,
    _risk_tips,
    _score_risk,
    assess_risk,
    lookup_cea_local,
    verify_cea_agent,
)

# ---------------------------------------------------------------------------
# lookup_cea_local
# ---------------------------------------------------------------------------


def test_lookup_finds_by_exact_registration_number():
    result = lookup_cea_local("reg_no", "P015022G")

    assert result["found"] is True
    assert result["source"] == "local_csv"
    assert len(result["records"]) == 1
    assert result["records"][0]["salesperson_name"].lower().startswith("wang soon yee")


def test_lookup_finds_by_partial_name():
    result = lookup_cea_local("name", "LARRY")

    assert result["found"] is True
    assert any("larry" in rec["salesperson_name"].lower() for rec in result["records"])


def test_lookup_case_insensitive():
    result = lookup_cea_local("name", "salbiah binte ramli")

    assert result["found"] is True
    assert len(result["records"]) >= 1


def test_lookup_not_found_for_unknown_name():
    result = lookup_cea_local("name", "AbsolutelyFake Person999")

    assert result["found"] is False
    assert result["source"] == "local_csv"
    assert "No match" in result.get("message", "")


def test_lookup_not_found_for_unknown_reg_no():
    result = lookup_cea_local("reg_no", "Z999999Z")

    assert result["found"] is False


def test_lookup_enriches_with_expiry_checks():
    result = lookup_cea_local("reg_no", "P015022G")

    rec = result["records"][0]
    assert "_is_expired" in rec
    assert "_days_to_expiry" in rec
    assert isinstance(rec["_is_expired"], bool)
    assert isinstance(rec["_days_to_expiry"], int)


def test_lookup_rejects_unsupported_query_type():
    result = lookup_cea_local("email", "test@test.com")

    assert result["found"] is False
    assert "Unsupported query_type" in result.get("message", "")


# ---------------------------------------------------------------------------
# verify_cea_agent (combined – API + CSV)
# ---------------------------------------------------------------------------


def test_verify_cea_agent_returns_source_key():
    """Live API call — may fail in CI; test validates response shape."""
    result = verify_cea_agent("reg_no", "P015022G")

    assert "source" in result
    assert result["source"] in {"api", "local_csv", "local_csv_fallback"}


def test_verify_falls_back_to_csv_for_unknown_name():
    result = verify_cea_agent("name", "TotallyFakeNameXYZ123")

    assert "source" in result
    assert result.get("found") is False or result.get("status") == "risk"


# ---------------------------------------------------------------------------
# _score_risk
# ---------------------------------------------------------------------------


def test_score_risk_high_when_not_found():
    verification = {"found": False, "records": [], "source": "local_csv"}
    result = _score_risk(verification)
    score, level, reasons = result["score"], result["risk_level"], result["reasons"]

    assert score < 45
    assert level == "high"
    assert any("NOT FOUND" in r for r in reasons)


def test_score_risk_low_for_verified_api_result():
    verification = {
        "status": "verified",
        "found": True,
        "source": "api",
        "records": [
            {
                "salesperson_name": "Test Agent",
                "registration_no": "R000001A",
                "registration_end_date": "2030-12-31",
                "_is_expired": False,
                "_days_to_expiry": 1700,
            }
        ],
    }
    result = _score_risk(verification)
    score, level, reasons = result["score"], result["risk_level"], result["reasons"]

    # 60 (status) + 25 (expiry) + 15 (api source) = 100
    assert score == 100.0
    assert level == "low"


def test_score_csv_source_lower_than_api():
    verification = {
        "status": "verified",
        "found": True,
        "source": "local_csv",
        "records": [
            {
                "salesperson_name": "Test Agent",
                "registration_no": "R000001A",
                "registration_end_date": "2030-12-31",
                "_is_expired": False,
                "_days_to_expiry": 1700,
            }
        ],
    }
    result = _score_risk(verification)
    score, level, reasons = result["score"], result["risk_level"], result["reasons"]

    # 60 + 25 + 8 = 93
    assert score == 93.0
    assert level == "low"


def test_score_penalises_expired_registration():
    verification = {
        "found": True,
        "source": "local_csv",
        "records": [
            {
                "salesperson_name": "Expired Agent",
                "registration_no": "R000002B",
                "registration_end_date": "2020-01-01",
                "_is_expired": True,
                "_days_to_expiry": -2300,
            }
        ],
    }
    result = _score_risk(verification)
    score, level, reasons = result["score"], result["risk_level"], result["reasons"]

    # 60 (found) + 0 (expired) + 8 (csv source) = 68
    assert score == 68.0
    assert level == "medium"


def test_score_penalises_near_expiry():
    verification = {
        "found": True,
        "source": "api",
        "records": [
            {
                "salesperson_name": "Soon Expired",
                "registration_no": "R000003C",
                "registration_end_date": "2026-06-30",
                "_is_expired": False,
                "_days_to_expiry": 60,
            }
        ],
    }
    result = _score_risk(verification)
    score, level, reasons = result["score"], result["risk_level"], result["reasons"]

    # 60 + 10 (near expiry) + 15 (api) = 85
    assert score == 85.0
    assert level == "low"


# ---------------------------------------------------------------------------
# _risk_tips
# ---------------------------------------------------------------------------


def test_risk_tips_emits_stop_warning_when_not_found():
    verification = {"found": False, "records": [], "source": "local_csv"}
    tips = _risk_tips(verification)

    assert any("STOP" in tip for tip in tips)
    assert any("NOT registered" in tip for tip in tips)


def test_risk_tips_mentions_csv_staleness():
    verification = {
        "found": True,
        "source": "local_csv_fallback",
        "records": [
            {
                "salesperson_name": "Test",
                "registration_no": "R000001A",
                "registration_end_date": "2030-12-31",
                "_is_expired": False,
                "_days_to_expiry": 1700,
            }
        ],
    }
    tips = _risk_tips(verification)
    assert any("cached local data" in tip.lower() for tip in tips)


def test_risk_tips_includes_address_crosscheck():
    verification = {"found": True, "records": [], "source": "api"}
    tips = _risk_tips(verification, address="123 Jurong West")

    assert any("cross" in tip.lower() for tip in tips)


# ---------------------------------------------------------------------------
# assess_risk (deterministic)
# ---------------------------------------------------------------------------


def test_assess_risk_verifies_by_agent_name():
    output = assess_risk(
        AgentInput(address="123 Jurong West"),
        agent_name="LARRY",
    )

    assert output.agent_name == "risk_agent"
    assert output.risk_level in {"low", "medium", "high", "unknown"}
    assert output.score is not None
    assert any("LARRY" in f for f in output.findings)
    assert len(output.recommendations) >= 1


def test_assess_risk_verifies_by_reg_no():
    output = assess_risk(
        AgentInput(address="123 Jurong West"),
        agent_reg_no="P015022G",
    )

    assert output.agent_name == "risk_agent"
    assert "P015022G" in str(output.findings)


def test_assess_risk_unknown_when_no_agent():
    output = assess_risk(AgentInput(address="123 Jurong West"))

    assert output.risk_level == "unknown"
    assert output.score is None
    assert output.data.get("verification") is None


def test_assess_risk_handles_empty_input():
    output = assess_risk({})

    assert output.agent_name == "risk_agent"
    assert output.risk_level == "unknown"
    assert output.score is None
    assert isinstance(output.findings, list)
    assert isinstance(output.recommendations, list)


def test_assess_risk_output_matches_schema():
    output = assess_risk(
        AgentInput(address="123 Jurong West"),
        agent_name="LARRY",
    )

    # Round-trip through Pydantic to validate schema
    validated = AgentOutput(**output.model_dump())
    assert validated.agent_name == "risk_agent"
    assert validated.risk_level in {"low", "medium", "high", "unknown"}


def test_assess_risk_extracts_name_from_contract_text():
    output = assess_risk(
        AgentInput(
            address="123 Jurong West",
            contract_text=(
                "TENANCY AGREEMENT\n"
                "Agent: WANG SOON YEE, LARRY\n"
                "CEA Reg No: P015022G\n"
            ),
        ),
    )

    assert output.risk_level in {"low", "medium", "high"}
    assert output.score is not None
    assert "WANG SOON YEE" in str(output.findings) or "P015022G" in str(output.findings)


# ---------------------------------------------------------------------------
# _extract_agent_name_from_text
# ---------------------------------------------------------------------------


def test_extract_name_after_agent_label():
    text = "Agent: John Tan (R123456A)\nAddress: 123 Main St"
    result = _extract_agent_name_from_text(text)
    assert result is not None
    assert "John Tan" in result


def test_extract_name_after_salesperson_label():
    text = "Salesperson: Alice Wong"
    result = _extract_agent_name_from_text(text)
    assert result is not None
    assert "Alice Wong" in result


def test_extract_name_returns_none_for_empty():
    assert _extract_agent_name_from_text("") is None
    assert _extract_agent_name_from_text(None) is None  # type: ignore[arg-type]


def test_extract_name_returns_none_when_no_match():
    text = "This is a standard tenancy agreement with no agent info."
    result = _extract_agent_name_from_text(text)
    assert result is None

