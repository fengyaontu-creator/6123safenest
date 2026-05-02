from agents import AgentInput
from agents.location_agent import assess_location, commute_estimate, nearest_mrt


def test_nearest_mrt_matches_jurong_west():
    result = nearest_mrt("123 Jurong West Street 65")

    assert result["found"] is True
    assert result["station"] == "Boon Lay"
    assert result["distance_km"] > 0


def test_commute_estimate_to_ntu():
    result = commute_estimate("123 Jurong West", "NTU")

    assert result["destination"] == "NTU"
    assert result["estimated_minutes"] <= 20


def test_location_agent_returns_schema_output():
    output = assess_location(AgentInput(address="123 Jurong West", rent=2000))

    assert output.agent_name == "location_agent"
    assert output.risk_level in {"low", "medium", "high"}
    assert output.score is not None
    assert "nearest_mrt" in output.data
