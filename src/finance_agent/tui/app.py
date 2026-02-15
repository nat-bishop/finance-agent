"""Textual app: initialization, screen registration, keybindings."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from claude_agent_sdk import (
    ClaudeSDKClient,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import PermissionResultAllow
from textual.app import App

from ..config import load_configs
from ..database import AgentDatabase
from ..hooks import create_audit_hooks
from ..kalshi_client import KalshiAPIClient
from ..main import build_options
from ..polymarket_client import PolymarketAPIClient
from ..tools import create_db_tools, create_market_tools
from .messages import AskUserQuestionRequest, RecommendationCreated
from .screens.dashboard import DashboardScreen
from .screens.history import HistoryScreen
from .screens.portfolio import PortfolioScreen
from .screens.recommendations import RecommendationsScreen
from .screens.signals import SignalsScreen
from .services import TUIServices

_WATCHLIST_PATH = Path("/workspace/data/watchlist.md")


class FinanceApp(App):
    """Cross-platform arbitrage analyst TUI."""

    TITLE = "Finance Agent"
    CSS_PATH = "agent.tcss"

    BINDINGS: ClassVar[list] = [
        ("f1", "switch_screen('dashboard')", "Chat"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: ClaudeSDKClient | None = None
        self._db: AgentDatabase | None = None
        self._services: TUIServices | None = None

    async def on_mount(self) -> None:
        """Initialize clients, DB, session, SDK client, then push dashboard."""
        agent_config, credentials, trading_config = load_configs()

        # Database
        db = AgentDatabase(trading_config.db_path)
        self._db = db
        backup_result = db.backup_if_needed(
            trading_config.backup_dir,
            max_age_hours=trading_config.backup_max_age_hours,
        )
        if backup_result:
            self.log(f"DB backup: {backup_result}")

        session_id = db.create_session()

        # Build startup context
        startup_state = db.get_session_state()
        startup_state["watchlist"] = (
            _WATCHLIST_PATH.read_text(encoding="utf-8") if _WATCHLIST_PATH.exists() else ""
        )
        active_markets = Path("/workspace/data/active_markets.md")
        startup_state["data_freshness"] = {
            "active_markets_updated_at": datetime.fromtimestamp(
                active_markets.stat().st_mtime, tz=UTC
            ).isoformat()
            if active_markets.exists()
            else None,
        }

        # Clear session scratch file
        session_log = Path("/workspace/data/session.log")
        session_log.parent.mkdir(parents=True, exist_ok=True)
        session_log.write_text("", encoding="utf-8")

        # Exchange clients
        kalshi = KalshiAPIClient(credentials, trading_config)
        polymarket_enabled = trading_config.polymarket_enabled and bool(
            credentials.polymarket_key_id
        )
        pm_client = (
            PolymarketAPIClient(credentials, trading_config) if polymarket_enabled else None
        )

        # Services
        services = TUIServices(
            db=db,
            kalshi=kalshi,
            polymarket=pm_client,
            config=trading_config,
            session_id=session_id,
        )
        self._services = services

        # MCP tools
        mcp_tools = {
            "markets": create_market_tools(kalshi, pm_client),
            "db": create_db_tools(db, session_id, trading_config.recommendation_ttl_minutes),
        }
        mcp_servers = {
            key: create_sdk_mcp_server(name=key, version="1.0.0", tools=tools)
            for key, tools in mcp_tools.items()
        }

        # Hooks with TUI callback
        hooks = create_audit_hooks(
            db=db,
            session_id=session_id,
            on_recommendation=lambda: self.post_message(RecommendationCreated()),
        )

        # AskUserQuestion handler
        app_ref = self

        async def can_use_tool_tui(
            tool_name: str, input_data: dict[str, Any], context: Any
        ) -> PermissionResultAllow:
            if tool_name == "AskUserQuestion":
                future: asyncio.Future[dict[str, str]] = asyncio.get_event_loop().create_future()
                app_ref.post_message(
                    AskUserQuestionRequest(
                        questions=input_data.get("questions", []),
                        future=future,
                    )
                )
                answers = await future
                return PermissionResultAllow(
                    updated_input={
                        "questions": input_data.get("questions", []),
                        "answers": answers,
                    }
                )
            return PermissionResultAllow(updated_input=input_data)

        # Build SDK options
        options = build_options(
            agent_config=agent_config,
            trading_config=trading_config,
            mcp_servers=mcp_servers,
            can_use_tool=can_use_tool_tui,
            hooks=hooks,
        )

        # Create SDK client
        client = ClaudeSDKClient(options=options)
        await client.__aenter__()
        self._client = client

        # Startup message
        startup_msg = f"BEGIN_SESSION\n\n{json.dumps(startup_state, indent=2)}"

        # Install all screens
        screens = {
            "dashboard": DashboardScreen(
                client=client,
                services=services,
                startup_msg=startup_msg,
                session_id=session_id,
            ),
            "recommendations": RecommendationsScreen(services=services),
            "portfolio": PortfolioScreen(services=services),
            "signals": SignalsScreen(services=services),
            "history": HistoryScreen(services=services),
        }
        for name, screen in screens.items():
            self.install_screen(screen, name=name)
        self.push_screen("dashboard")

    async def on_unmount(self) -> None:
        """Clean up SDK client and database."""
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
        if self._db:
            self._db.close()
