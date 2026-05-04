import asyncio
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents import AgentInput
import main


class _FakeSession:
    id = "session-1"
    state = {}


class _FakeSessionService:
    async def create_session(self, **kwargs):
        self.create_kwargs = kwargs
        return _FakeSession()

    async def get_session(self, **kwargs):
        return _FakeSession()


class _FakePart:
    text = "runner final report"


class _FakeContent:
    parts = [_FakePart()]


class _FakeEvent:
    content = _FakeContent()

    def is_final_response(self):
        return True


class _FakeRunner:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run_async(self, **kwargs):
        self.run_kwargs = kwargs
        yield _FakeEvent()


def test_main_uses_adk_runner(monkeypatch):
    monkeypatch.setattr(main, "InMemorySessionService", _FakeSessionService)
    monkeypatch.setattr(main, "Runner", _FakeRunner)

    result = asyncio.run(
        main.run_with_adk_runner(AgentInput(address="123 Jurong West", rent=2000))
    )

    assert result == "runner final report"

