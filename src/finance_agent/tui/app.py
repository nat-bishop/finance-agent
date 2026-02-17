"""Textual app: initialization, screen registration, keybindings."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from claude_agent_sdk import (
    ClaudeSDKClient,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import PermissionResultAllow
from textual.app import App

from ..config import AgentConfig, TradingConfig, load_configs
from ..database import AgentDatabase
from ..hooks import create_audit_hooks
from ..kalshi_client import KalshiAPIClient
from ..main import build_options
from ..tools import create_db_tools, create_market_tools
from .messages import AskUserQuestionRequest, RecommendationCreated
from .screens.dashboard import DashboardScreen
from .screens.history import HistoryScreen
from .screens.portfolio import PortfolioScreen
from .screens.recommendations import RecommendationsScreen
from .services import TUIServices
from .widgets.agent_chat import AgentChat
from .widgets.status_bar import StatusBar

_KB_PATH = Path("/workspace/analysis/knowledge_base.md")
logger = logging.getLogger(__name__)


class FinanceApp(App):
    """Kalshi market analyst TUI."""

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
        self._session_id: str | None = None
        self._agent_config: AgentConfig | None = None
        self._trading_config: TradingConfig | None = None
        self._kalshi: KalshiAPIClient | None = None
        self._can_use_tool: Any = None

    async def on_mount(self) -> None:
        """Initialize clients, DB, session, SDK client, then push dashboard."""
        try:
            await self._init_app()
        except Exception:
            logger.exception("on_mount failed — app will show a blank screen")
            raise

    async def _init_app(self) -> None:
        agent_config, credentials, trading_config = load_configs()
        self._agent_config = agent_config
        self._trading_config = trading_config

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
        self._session_id = session_id

        # Exchange clients
        kalshi = KalshiAPIClient(credentials, trading_config)
        self._kalshi = kalshi

        # Services
        services = TUIServices(
            db=db,
            kalshi=kalshi,
            config=trading_config,
            session_id=session_id,
            credentials=credentials,
        )
        self._services = services

        # AskUserQuestion handler (closure over self, reusable across resets)
        async def can_use_tool_tui(
            tool_name: str, input_data: dict[str, Any], context: Any
        ) -> PermissionResultAllow:
            if tool_name == "AskUserQuestion":
                future: asyncio.Future[dict[str, str]] = asyncio.get_event_loop().create_future()
                self.post_message(
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

        self._can_use_tool = can_use_tool_tui

        # Build SDK client with session context in system prompt
        session_context = await self._build_session_context()
        client = self._build_client(session_id, session_context=session_context)
        await client.__aenter__()
        self._client = client

        # Install all screens
        screens = {
            "dashboard": DashboardScreen(
                client=client,
                services=services,
                session_id=session_id,
            ),
            "recommendations": RecommendationsScreen(services=services),
            "portfolio": PortfolioScreen(services=services),
            "history": HistoryScreen(services=services),
        }
        for name, screen in screens.items():
            self.install_screen(screen, name=name)
        self.push_screen("dashboard")

    async def _build_session_context(self) -> str:
        """Build dynamic session context for the system prompt."""
        db = self._db
        if not db:
            return ""

        session_state = db.get_session_state()
        kb = _KB_PATH.read_text(encoding="utf-8") if _KB_PATH.exists() else ""

        portfolio: dict[str, Any] | None = None
        if self._services:
            try:
                portfolio = await self._services.get_portfolio()
            except Exception:
                logger.debug("Could not fetch portfolio for session context", exc_info=True)

        parts = ["## Session Context"]
        if session_state.get("last_session"):
            parts.append(
                f"### Last Session\n```json\n"
                f"{json.dumps(session_state['last_session'], indent=2, default=str)}\n```"
            )
        if session_state.get("unreconciled_trades"):
            parts.append(
                f"### Unreconciled Trades\n```json\n"
                f"{json.dumps(session_state['unreconciled_trades'], indent=2, default=str)}\n```"
            )
        if portfolio:
            parts.append(
                f"### Portfolio\n```json\n{json.dumps(portfolio, indent=2, default=str)}\n```"
            )
        if kb:
            parts.append(f"### Knowledge Base\n\n{kb}")

        return "\n\n".join(parts)

    def _build_client(self, session_id: str, session_context: str = "") -> ClaudeSDKClient:
        """Build a new SDK client with fresh MCP servers and hooks."""
        db = self._db
        kalshi = self._kalshi
        trading_config = self._trading_config
        agent_config = self._agent_config
        if not db or not kalshi or not trading_config or not agent_config:
            raise RuntimeError("Cannot build client before _init_app completes")

        mcp_tools = {
            "markets": create_market_tools(kalshi),
            "db": create_db_tools(
                db,
                session_id,
                kalshi,
                trading_config,
                trading_config.recommendation_ttl_minutes,
            ),
        }
        mcp_servers = {
            key: create_sdk_mcp_server(name=key, version="1.0.0", tools=tools)
            for key, tools in mcp_tools.items()
        }
        hooks = create_audit_hooks(
            db=db,
            session_id=session_id,
            on_recommendation=lambda: self.post_message(RecommendationCreated()) or None,  # type: ignore[arg-type]
        )
        options = build_options(
            agent_config=agent_config,
            trading_config=trading_config,
            mcp_servers=mcp_servers,
            can_use_tool=self._can_use_tool,
            hooks=hooks,
            session_context=session_context,
        )
        return ClaudeSDKClient(options=options)

    async def action_reset_session(self) -> None:
        """Reset the agent session: new client, new DB session, clear UI."""
        if not self._db:
            return

        # End current session
        if self._session_id:
            with contextlib.suppress(Exception):
                self._db.end_session(
                    self._session_id,
                    summary="Reset by user",
                    recommendations_made=0,
                )

        # Disconnect old client
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)

        # New DB session
        session_id = self._db.create_session()
        self._session_id = session_id
        if self._services:
            self._services._session_id = session_id

        # New SDK client with fresh session context
        session_context = await self._build_session_context()
        client = self._build_client(session_id, session_context=session_context)
        await client.__aenter__()
        self._client = client

        # Reset widgets in-place
        dashboard: DashboardScreen = self.get_screen("dashboard")  # type: ignore[assignment]
        dashboard._client = client
        dashboard._session_id = session_id
        dashboard.query_one("#agent-chat", AgentChat).reset(client)
        bar = dashboard.query_one("#status-bar", StatusBar)
        bar.session_id = session_id
        bar.total_cost = 0.0
        bar.rec_count = 0

        logger.info("Session reset — new session: %s", session_id)

    async def on_unmount(self) -> None:
        """Clean up SDK client, session state, and database."""
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
        if self._services and self._services._fill_monitor:
            with contextlib.suppress(Exception):
                await self._services._fill_monitor.close()
        if self._db and self._session_id:
            with contextlib.suppress(Exception):
                # Only end session if not already ended by the Stop hook
                from ..models import Session

                with self._db._session_factory() as sess:
                    row = sess.get(Session, self._session_id)
                    if row and row.ended_at is None:
                        self._db.end_session(
                            self._session_id,
                            summary="App closed",
                            recommendations_made=0,
                        )
        if self._db:
            self._db.close()
