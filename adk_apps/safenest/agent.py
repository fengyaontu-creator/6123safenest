"""ADK Web discovery entry for SafeNest."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.orchestrator import root_agent as safenest_workflow
from config import settings
from google.adk.agents import LlmAgent


root_agent = LlmAgent(
    name="safenest",
    model=settings.web_entry_model,
    instruction=(
        "You are the SafeNest web entry agent. For rental assessment requests, "
        "delegate to the safenest_root workflow, which runs intake, specialist "
        "agents, and synthesis. Your only available action is transferring to a "
        "sub-agent. Never call run_code, execute code, inspect local files, or "
        "attempt to parse uploaded PDFs yourself. If the user uploads a PDF, treat "
        "it as an attachment signal only; the current baseline workflow needs the "
        "contract PDF path or a text summary from the user."
    ),
    sub_agents=[safenest_workflow],
)


__all__ = ["root_agent"]
