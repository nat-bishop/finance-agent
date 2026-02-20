"""Textual app: thin WS client connecting to the agent server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, ClassVar

import websockets
import websockets.asyncio.client
from textual.app import App
from textual.css.query import NoMatches

from ..config import AgentConfig, TradingConfig, load_configs
from ..database import AgentDatabase
from ..kalshi_client import KalshiAPIClient
from .messages import (
    AgentResultReceived,
    AgentTextReceived,
    AgentToolResult,
    AgentToolUse,
    AskQuestionReceived,
    RecommendationCreated,
    SessionReset,
)
from .screens.dashboard import DashboardScreen
from .screens.history import HistoryScreen
from .screens.knowledge_base import KnowledgeBaseScreen
from .screens.performance import PerformanceScreen
from .screens.portfolio import PortfolioScreen
from .screens.recommendations import RecommendationsScreen
from .services import TUIServices

logger = logging.getLogger(__name__)


class FinanceApp(App):
    """Kalshi market analyst TUI — WebSocket client to agent server."""

    TITLE = "Finance Agent"
    CSS_PATH = "agent.tcss"

    BINDINGS: ClassVar[list] = [
        ("f1", "switch_screen('dashboard')", "Chat"),
        ("f6", "switch_screen('performance')", "P&L"),
    ]

    def __init__(self, ws_url: str = "ws://localhost:8765", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ws_url = ws_url
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._ws_listener_task: asyncio.Task[None] | None = None
        self._db: AgentDatabase | None = None
        self._services: TUIServices | None = None
        self._session_id: str | None = None
        self._agent_config: AgentConfig | None = None
        self._trading_config: TradingConfig | None = None
        self._kalshi: KalshiAPIClient | None = None

    async def on_mount(self) -> None:
        """Connect to server, initialize local resources, install screens."""
        try:
            await self._init_app()
        except Exception:
            logger.exception("on_mount failed — app will show a blank screen")
            raise

    async def _init_app(self) -> None:
        agent_config, credentials, trading_config = load_configs()
        self._agent_config = agent_config
        self._trading_config = trading_config

        # Local database connection (for TUI screens: recs, portfolio, history)
        db = AgentDatabase(trading_config.db_path)
        self._db = db

        # Exchange client (for TUI: portfolio display + trade execution)
        kalshi = KalshiAPIClient(credentials, trading_config)
        self._kalshi = kalshi

        # Services (execution, portfolio reads, DB queries)
        services = TUIServices(
            db=db,
            kalshi=kalshi,
            config=trading_config,
            session_id="pending",  # updated on WS connect
            credentials=credentials,
        )
        self._services = services

        # Per-session file logging
        self._log_handler: logging.Handler | None = None
        if trading_config.log_dir:
            from ..logging_config import add_session_file_handler

            self._log_handler = add_session_file_handler(trading_config.log_dir, "tui")
            logger.info("TUI started")

        # Install screens BEFORE connecting WS (so widgets exist for messages)
        screens = {
            "dashboard": DashboardScreen(
                services=services,
                session_id="connecting...",
            ),
            "knowledge_base": KnowledgeBaseScreen(
                analysis_dir=trading_config.analysis_dir,
            ),
            "recommendations": RecommendationsScreen(services=services),
            "portfolio": PortfolioScreen(services=services),
            "history": HistoryScreen(services=services),
            "performance": PerformanceScreen(services=services),
        }
        for name, screen in screens.items():
            self.install_screen(screen, name=name)
        self.push_screen("dashboard")

        # Connect to agent server AFTER screens are installed
        ws = await websockets.connect(self._ws_url)
        self._ws = ws

        # Start WS listener after dashboard is active
        self._ws_listener_task = asyncio.create_task(self._ws_listener())

    def _post_to_widget(self, selector: str, message: Any) -> None:
        """Post a message directly to a widget by CSS selector."""
        try:
            self.screen.query_one(selector).post_message(message)
        except NoMatches:
            logger.debug("Widget %s not mounted — dropped %s", selector, type(message).__name__)
        except Exception:
            logger.exception("_post_to_widget failed for %s", selector)

    def _post_to_screen(self, message: Any) -> None:
        """Post a message to the active screen."""
        try:
            self.screen.post_message(message)
        except Exception:
            logger.debug("Screen dispatch failed — dropped %s", type(message).__name__)

    async def _ws_listener(self) -> None:
        """Background task: consume WS messages from server, dispatch to widgets."""
        ws = self._ws
        if not ws:
            return

        try:
            async for raw in ws:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                logger.debug("WS recv: %s", msg_type)

                if msg_type == "text":
                    self._post_to_widget("#agent-chat", AgentTextReceived(msg["content"]))

                elif msg_type == "tool_use":
                    self._post_to_widget(
                        "#agent-chat",
                        AgentToolUse(msg["name"], msg["id"], msg.get("input", {})),
                    )

                elif msg_type == "tool_result":
                    self._post_to_widget(
                        "#agent-chat",
                        AgentToolResult(
                            msg["id"], msg.get("content", ""), msg.get("is_error", False)
                        ),
                    )

                elif msg_type == "result":
                    self._post_to_widget(
                        "#agent-chat",
                        AgentResultReceived(
                            msg.get("total_cost_usd", 0),
                            msg.get("is_error", False),
                        ),
                    )

                elif msg_type == "ask_question":
                    self._post_to_screen(AskQuestionReceived(msg["request_id"], msg["questions"]))

                elif msg_type == "recommendation_created":
                    self._post_to_screen(RecommendationCreated())

                elif msg_type == "session_reset":
                    new_id = msg["session_id"]
                    self._session_id = new_id
                    if self._services:
                        self._services._session_id = new_id
                    self._post_to_screen(SessionReset(new_id))

                elif msg_type == "session_log_saved":
                    logger.info(
                        "Session log saved: %s -> %s",
                        msg["session_id"],
                        msg.get("path", ""),
                    )

                elif msg_type == "status":
                    self._session_id = msg.get("session_id")
                    if self._services and self._session_id:
                        self._services._session_id = self._session_id
                    self._post_to_screen(SessionReset(self._session_id or ""))

                else:
                    logger.debug("Unknown WS message type: %s", msg_type)

        except websockets.ConnectionClosed:
            logger.warning("WebSocket connection to server lost")
        except asyncio.CancelledError:
            logger.info("WS listener cancelled")
        except Exception:
            logger.exception("WS listener crashed")

    async def send_ws(self, data: dict[str, Any]) -> None:
        """Send a JSON message to the agent server."""
        if self._ws:
            try:
                await self._ws.send(json.dumps(data, default=str))
            except websockets.ConnectionClosed:
                logger.warning("Cannot send — WS connection closed")
                self._ws = None

    async def action_clear_chat(self) -> None:
        """Send clear command to server (it handles session rotation)."""
        await self.send_ws({"type": "clear"})

    async def on_unmount(self) -> None:
        """Clean up WS connection and local resources."""
        if self._ws_listener_task:
            self._ws_listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_listener_task

        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()

        if self._services and self._services._fill_monitor:
            with contextlib.suppress(BaseException):
                await self._services._fill_monitor.close()

        if self._db:
            with contextlib.suppress(BaseException):
                self._db.close()

        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler.close()
