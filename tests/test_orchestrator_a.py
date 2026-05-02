from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import root_agent, run_offline_assessment, run_offline_report
from agents.synthesizer import synthesizer_agent


def test_root_agent_uses_parallel_then_synthesizer():
    assert root_agent.name == "safenest_root"
    assert len(root_agent.sub_agents) == 2

    assert root_agent.sub_agents[0].name == "intake_extractor"

    analysis_workflow = root_agent.sub_agents[1]
    assert analysis_workflow.name == "safenest_analysis_workflow"
    assert len(analysis_workflow.sub_agents) == 2

    parallel = analysis_workflow.sub_agents[0]
    assert parallel.name == "safenest_parallel_specialists"
    assert [agent.name for agent in parallel.sub_agents] == [
        "location_agent",
        "contract_agent",
        "price_agent",
        "risk_agent",
    ]
    assert analysis_workflow.sub_agents[1].name == "synthesizer"


def test_offline_assessment_combines_agent_outputs():
    output = run_offline_assessment({"address": "123 Jurong West", "rent": 2000})

    assert output.agent_name == "synthesizer"
    assert output.risk_level in {"low", "medium", "high", "unknown"}
    assert "location_agent" in output.data["agents"]


def test_offline_report_is_human_readable():
    report = run_offline_report({"address": "123 Jurong West", "rent": 2000})

    assert "SafeNest Rental Assessment" in report
    assert "Nearest MRT" in report


def test_synthesizer_instruction_reads_adk_state_keys():
    assert "location_output" in synthesizer_agent.instruction
    assert "contract_output" in synthesizer_agent.instruction
    assert "price_output" in synthesizer_agent.instruction
    assert "risk_output" in synthesizer_agent.instruction
    assert "{location_output}" not in synthesizer_agent.instruction
