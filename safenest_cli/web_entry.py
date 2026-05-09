"""Poetry script entry for SafeNest ADK Web."""

from __future__ import annotations

from google.adk.cli.cli_tools_click import main as adk_main


def main() -> None:
    """Run ADK Web with SafeNest's preferred in-memory services."""

    adk_main(
        args=[
            "web",
            "--session_service_uri=memory://",
            "--artifact_service_uri=memory://",
            "adk_apps",
        ],
        prog_name="adk",
        standalone_mode=True,
    )
