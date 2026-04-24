"""ui — FastAPI app, HTML pages, Slack adapter.

Talks to orchestration only via `orchestration.api`.
"""

from ui.server.app import create_app

__all__ = ["create_app"]
