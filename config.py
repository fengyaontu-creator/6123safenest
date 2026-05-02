"""Global configuration for SafeNest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


@dataclass(frozen=True)
class Settings:
    app_name: str = "safenest"
    runner_app_name: str = "agents"
    specialist_model: str = "gemini-2.5-flash-lite"
    synthesizer_model: str = "gemini-2.5-flash"
    web_entry_model: str = "gemini-2.5-flash-lite"
    mrt_stations_path: Path = DATA_DIR / "mrt_stations.json"
    listings_path: Path = DATA_DIR / "listings.csv"
    cea_agents_path: Path = DATA_DIR / "cea_agents.csv"


settings = Settings()
