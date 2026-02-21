"""WebSocket agent server — persistent Claude SDK client with session logging."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import websockets
import websockets.asyncio.server
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import PermissionResultAllow

from .config import AgentConfig, Credentials, TradingConfig
from .database import AgentDatabase
from .hooks import create_audit_hooks
from .kalshi_client import KalshiAPIClient
from .main import build_options
from .tools import create_db_tools, create_market_tools

logger = logging.getLogger(__name__)

_EXTRACTION_TIMEOUT = 20  # seconds, must fit within Docker stop_grace_period (30s)

_WRAP_UP_PROMPT = (
    "This session is ending. Summarize ONLY what happened in THIS conversation — "
    "do not repeat information from prior sessions injected into your system prompt. Cover:\n"
    "- What you investigated and your approach\n"
    "- Key findings and insights\n"
    "- Any recommendations you made\n"
    "- Open questions or areas worth exploring in future sessions"
)


class AgentServer:
    """WebSocket server managing the Claude SDK agent lifecycle."""

    def __init__(
        self,
        agent_config: AgentConfig,
        trading_config: TradingConfig,
        credentials: Credentials,
    ) -> None:
        self._agent_config = agent_config
        self._trading_config = trading_config
        self._credentials = credentials

        self._db: AgentDatabase | None = None
        self._kalshi: KalshiAPIClient | None = None
        self._client: ClaudeSDKClient | None = None
        self._session_id: str | None = None

        workspace = Path(agent_config.workspace)
        self._kb_path = workspace / "analysis" / "knowledge_base.md"
        self._session_log_dir = workspace / "analysis" / "sessions"

        self._ws_client: websockets.asyncio.server.ServerConnection | None = None
        self._chat_task: asyncio.Task[None] | None = None
        self._rec_notify_task: asyncio.Task[None] | None = None
        self._ask_futures: dict[str, asyncio.Future[dict[str, str]]] = {}
        self._shutting_down: bool = False
        self._streaming: bool = False
        self._rotation_lock = asyncio.Lock()
        self._session_message_count: int = 0
        self._sdk_session_id: str | None = None

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize resources and start the WebSocket server."""
        # Database
        self._db = AgentDatabase(self._trading_config.db_path)
        backup = self._db.backup_if_needed(
            self._trading_config.backup_dir,
            max_age_hours=self._trading_config.backup_max_age_hours,
        )
        if backup:
            logger.info("DB backup: %s", backup)

        # Exchange client
        self._kalshi = KalshiAPIClient(self._credentials, self._trading_config)

        # Deferred extraction for sessions that missed logging (crash recovery)
        await self._deferred_extraction()

        # Create initial session + SDK client
        await self._new_session()

        # Handle graceful shutdown signals (not supported on Windows)
        loop = asyncio.get_running_loop()
        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))
        except NotImplementedError:
            logger.debug("Signal handlers not supported on this platform")

        port = self._agent_config.server_port
        logger.info("WebSocket server listening on %d", port)

        async with websockets.serve(self._handle_ws, "0.0.0.0", port):  # noqa: S104
            # Run forever (until shutdown)
            await asyncio.Future()

    async def _shutdown(self) -> None:
        """Graceful shutdown: extract session log, clean up."""
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down...")

        # Cancel pending ask futures
        self._cancel_ask_futures()

        # Extract final session log (with timeout)
        if self._client and self._session_id:
            try:
                await asyncio.wait_for(
                    self._extract_session_log(self._session_id),
                    timeout=_EXTRACTION_TIMEOUT,
                )
            except TimeoutError:
                logger.warning("Session log extraction timed out during shutdown")

        # Destroy client
        if self._client:
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
            self._client = None

        # Close DB
        if self._db:
            with contextlib.suppress(Exception):
                self._db.close()

        logger.info("Shutdown complete")
        raise SystemExit(0)

    # ── Session management ────────────────────────────────────────

    async def _new_session(self) -> None:
        """Create a new DB session and SDK client."""
        if not self._db:
            raise RuntimeError("Database not initialized")

        session_id = self._db.create_session()
        self._session_id = session_id
        self._session_message_count = 0
        self._sdk_session_id = None
        logger.info("New session: %s", session_id)

        session_context = await self._build_session_context()
        client = self._build_client(session_id, session_context)
        await client.__aenter__()
        self._client = client

    async def _rotate_session(self) -> None:
        """Extract session log, destroy old client, create new session.

        Serialized via ``_rotation_lock`` so concurrent clears
        cannot race each other.
        """
        async with self._rotation_lock:
            if not self._client or not self._session_id:
                return

            old_session_id = self._session_id

            # Cancel active chat and pending ask futures from old session
            await self._cancel_chat_task()
            self._cancel_ask_futures()

            # Extract session log (with timeout)
            try:
                await asyncio.wait_for(
                    self._extract_session_log(old_session_id),
                    timeout=_EXTRACTION_TIMEOUT,
                )
            except TimeoutError:
                logger.warning("Session log extraction timed out for %s", old_session_id)

            # Destroy old client
            with contextlib.suppress(Exception):
                await self._client.__aexit__(None, None, None)
            self._client = None

            # Create new session + client
            await self._new_session()

            await self._send_ws(
                {
                    "type": "session_reset",
                    "session_id": self._session_id,
                }
            )

            logger.info("Session rotated: %s → %s", old_session_id, self._session_id)

    def _cancel_ask_futures(self) -> None:
        """Cancel all pending AskUserQuestion futures."""
        for future in self._ask_futures.values():
            if not future.done():
                future.cancel()
        self._ask_futures.clear()

    async def _build_session_context(self) -> str:
        """Build dynamic session context for the system prompt."""
        db = self._db
        if not db or not self._kalshi:
            return ""

        session_state = db.get_session_state(current_session_id=self._session_id)
        kb = self._kb_path.read_text(encoding="utf-8") if self._kb_path.exists() else ""

        portfolio: dict[str, Any] | None = None
        try:
            portfolio = {
                "kalshi": {
                    "balance": await self._kalshi.get_balance(),
                    "positions": await self._kalshi.get_positions(),
                }
            }
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
        if not db or not kalshi:
            raise RuntimeError("Cannot build client before start()")

        mcp_tools = {
            "markets": create_market_tools(kalshi),
            "db": create_db_tools(
                db,
                session_id,
                kalshi,
                self._trading_config,
                self._trading_config.recommendation_ttl_minutes,
            ),
        }
        mcp_servers = {
            key: create_sdk_mcp_server(name=key, version="1.0.0", tools=tools)
            for key, tools in mcp_tools.items()
        }
        hooks = create_audit_hooks(
            on_recommendation=self._on_recommendation,
        )
        options = build_options(
            agent_config=self._agent_config,
            trading_config=self._trading_config,
            mcp_servers=mcp_servers,
            can_use_tool=self._can_use_tool,
            hooks=hooks,
            workspace=self._agent_config.workspace,
            session_context=session_context,
        )
        return ClaudeSDKClient(options=options)

    def _on_recommendation(self) -> None:
        """Hook callback when recommend_trade succeeds."""
        self._rec_notify_task = asyncio.create_task(
            self._send_ws({"type": "recommendation_created"})
        )

    # ── WebSocket handler ─────────────────────────────────────────

    async def _handle_ws(self, websocket: websockets.asyncio.server.ServerConnection) -> None:
        """Handle a single TUI client connection."""
        if self._ws_client is not None:
            logger.warning("New TUI connection replacing existing one")
            with contextlib.suppress(Exception):
                await self._ws_client.close(1000, "replaced")

        self._ws_client = websocket
        logger.info("TUI client connected")

        # Send status on connect
        await self._send_ws(
            {
                "type": "status",
                "session_id": self._session_id,
                "connected": True,
            }
        )

        try:
            async for raw in websocket:
                msg = json.loads(raw)
                msg_type = msg.get("type")
                logger.debug("WS recv: %s", msg_type)

                if msg_type == "chat":
                    if self._chat_task and not self._chat_task.done():
                        logger.warning("Chat already in progress, ignoring")
                        continue
                    self._chat_task = asyncio.create_task(
                        self._handle_chat(msg.get("content", ""))
                    )
                elif msg_type == "clear":
                    await self._cancel_chat_task()
                    await self._handle_clear()
                elif msg_type == "interrupt":
                    await self._handle_interrupt()
                elif msg_type == "ask_response":
                    self._handle_ask_response(msg)
                else:
                    logger.warning("Unknown WS message type: %s", msg_type)
        except websockets.ConnectionClosed:
            logger.info("TUI client disconnected")
        finally:
            await self._cancel_chat_task()
            self._ws_client = None

    async def _send_ws(self, data: dict[str, Any]) -> None:
        """Send a JSON message to the connected TUI client."""
        if self._ws_client:
            try:
                await self._ws_client.send(json.dumps(data, default=str))
            except websockets.ConnectionClosed:
                self._ws_client = None

    # ── Message handlers ──────────────────────────────────────────

    async def _cancel_chat_task(self) -> None:
        """Cancel a running chat task if any."""
        if self._chat_task and not self._chat_task.done():
            self._chat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._chat_task
        self._chat_task = None

    async def _handle_chat(self, content: str) -> None:
        """Process a user chat message."""
        if not content:
            logger.warning("Empty chat message, ignoring")
            return
        if not self._client:
            logger.warning("No SDK client available, ignoring chat")
            return

        logger.info("Chat: %s", content[:120])
        self._streaming = True
        self._session_message_count += 1

        try:
            await self._client.query(content)
            logger.debug("Query sent, streaming response...")
            msg_count = 0
            result_cost = 0.0
            result_error = False
            async for msg in self._client.receive_response():
                msg_count += 1
                logger.debug("SDK message #%d: %s", msg_count, type(msg).__name__)
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            await self._send_ws(
                                {
                                    "type": "text",
                                    "content": block.text,
                                }
                            )
                        elif isinstance(block, ToolUseBlock):
                            logger.info(
                                "Tool call: %s(%s)",
                                block.name,
                                str(block.input)[:200] if block.input else "",
                            )
                            await self._send_ws(
                                {
                                    "type": "tool_use",
                                    "name": block.name,
                                    "id": block.id,
                                    "input": block.input,
                                }
                            )
                elif isinstance(msg, UserMessage):
                    for block in msg.content if isinstance(msg.content, list) else []:
                        if isinstance(block, ToolResultBlock):
                            logger.info(
                                "Tool result: %s (error=%s)",
                                str(block.content)[:200] if block.content else "",
                                block.is_error,
                            )
                            await self._send_ws(
                                {
                                    "type": "tool_result",
                                    "id": block.tool_use_id,
                                    "content": (str(block.content)[:500] if block.content else ""),
                                    "is_error": block.is_error,
                                }
                            )
                elif isinstance(msg, ResultMessage):
                    result_cost = msg.total_cost_usd or 0.0
                    result_error = msg.is_error
                    # Capture SDK session ID on first result
                    if not self._sdk_session_id and msg.session_id:
                        self._sdk_session_id = msg.session_id
                        if self._db and self._session_id:
                            self._db.update_sdk_session_id(self._session_id, msg.session_id)
                    await self._send_ws(
                        {
                            "type": "result",
                            "total_cost_usd": result_cost,
                            "is_error": result_error,
                        }
                    )
            logger.info(
                "Response complete (%d messages, cost=$%.4f, error=%s)",
                msg_count,
                result_cost,
                result_error,
            )
        except asyncio.CancelledError:
            logger.info("Chat task cancelled")
            with contextlib.suppress(Exception):
                await self._send_ws({"type": "result", "total_cost_usd": 0, "is_error": False})
            raise
        except Exception as exc:
            logger.exception("Error streaming agent response")
            await self._send_ws(
                {
                    "type": "result",
                    "total_cost_usd": 0,
                    "is_error": True,
                    "error": str(exc),
                }
            )
        finally:
            self._streaming = False

    async def _handle_clear(self) -> None:
        """Reset the conversation: extract log, destroy client, create new session."""
        await self._rotate_session()

    async def _handle_interrupt(self) -> None:
        """Interrupt the current agent response."""
        logger.info("Interrupt requested")
        if self._client:
            try:
                await self._client.interrupt()
            except Exception as exc:
                logger.warning("Interrupt failed: %s", exc)
        await self._cancel_chat_task()

    def _handle_ask_response(self, msg: dict[str, Any]) -> None:
        """Resolve a pending AskUserQuestion future."""
        request_id = msg.get("request_id", "")
        answers = msg.get("answers", {})
        future = self._ask_futures.pop(request_id, None)
        if future and not future.done():
            future.set_result(answers)
        else:
            logger.warning("No pending ask future for request_id=%s", request_id)

    # ── can_use_tool ──────────────────────────────────────────────

    async def _can_use_tool(
        self, tool_name: str, input_data: dict[str, Any], context: Any
    ) -> PermissionResultAllow:
        """Permission handler — bridges AskUserQuestion to TUI via WebSocket."""
        if tool_name == "AskUserQuestion":
            request_id = str(uuid.uuid4())[:8]
            future: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()
            self._ask_futures[request_id] = future

            await self._send_ws(
                {
                    "type": "ask_question",
                    "request_id": request_id,
                    "questions": input_data.get("questions", []),
                }
            )

            # Wait for TUI to respond (with timeout)
            try:
                answers = await asyncio.wait_for(future, timeout=300)
            except TimeoutError:
                answers = {}

            return PermissionResultAllow(
                updated_input={
                    "questions": input_data.get("questions", []),
                    "answers": answers,
                }
            )
        return PermissionResultAllow(updated_input=input_data)

    # ── Session log extraction ────────────────────────────────────

    async def _extract_session_log(self, session_id: str) -> None:
        """Send wrap-up prompt, capture prose, write to file and DB."""
        if not self._client or not self._db:
            return

        if self._session_message_count == 0:
            logger.info("Session %s had no messages — skipping log extraction", session_id)
            return

        logger.info("Extracting session log for %s...", session_id)

        try:
            await self._client.query(_WRAP_UP_PROMPT)
            parts: list[str] = []
            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    parts.extend(
                        block.text for block in msg.content if isinstance(block, TextBlock)
                    )

            content = "\n\n".join(parts).strip()
            if not content:
                logger.warning("Session log extraction produced no content")
                self._write_session_log(
                    self._db, session_id, "Session ended without summary (empty extraction)."
                )
                return

            self._write_session_log(self._db, session_id, content)

            # Notify TUI
            md_path = self._session_log_dir / f"{session_id}.md"
            await self._send_ws(
                {
                    "type": "session_log_saved",
                    "session_id": session_id,
                    "path": str(md_path),
                }
            )

        except Exception:
            logger.exception("Failed to extract session log for %s", session_id)

    # ── Deferred extraction (crash recovery) ─────────────────────

    async def _deferred_extraction(self) -> None:
        """On startup, extract logs for sessions that missed logging."""
        db = self._db
        if not db:
            return

        unlogged = db.get_unlogged_sessions()
        if not unlogged:
            return

        logger.info("Found %d unlogged session(s), attempting deferred extraction", len(unlogged))

        for sess in unlogged:
            sid = sess["id"]
            sdk_sid = sess.get("sdk_session_id")

            if not sdk_sid:
                logger.info("Session %s has no SDK session ID — writing stub", sid)
                self._write_session_log(
                    db, sid, "Session ended without summary (no SDK session available)."
                )
                continue

            try:
                await asyncio.wait_for(
                    self._resume_and_extract(db, sid, sdk_sid),
                    timeout=_EXTRACTION_TIMEOUT,
                )
            except TimeoutError:
                logger.warning("Deferred extraction timed out for %s", sid)
                self._write_session_log(
                    db, sid, "Session ended without summary (deferred extraction timed out)."
                )
            except Exception:
                logger.exception("Deferred extraction failed for %s", sid)
                self._write_session_log(
                    db, sid, "Session ended without summary (deferred extraction failed)."
                )

    async def _resume_and_extract(
        self, db: AgentDatabase, session_id: str, sdk_session_id: str
    ) -> None:
        """Resume an old SDK session and run the wrap-up prompt."""
        from claude_agent_sdk import ClaudeAgentOptions

        logger.info("Resuming SDK session %s for deferred extraction...", sdk_session_id)
        options = ClaudeAgentOptions(
            model=self._agent_config.model,
            cwd=self._agent_config.workspace,
            resume=sdk_session_id,
            max_budget_usd=1.0,
        )
        client = ClaudeSDKClient(options=options)
        try:
            await client.__aenter__()
            await client.query(_WRAP_UP_PROMPT)
            parts: list[str] = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    parts.extend(
                        block.text for block in msg.content if isinstance(block, TextBlock)
                    )

            content = "\n\n".join(parts).strip()
            if content:
                self._write_session_log(db, session_id, content)
                logger.info("Deferred extraction succeeded for %s", session_id)
            else:
                self._write_session_log(
                    db, session_id, "Session ended without summary (empty extraction)."
                )
        finally:
            with contextlib.suppress(Exception):
                await client.__aexit__(None, None, None)

    def _write_session_log(self, db: AgentDatabase, session_id: str, content: str) -> None:
        """Write session log to both markdown file and DB."""
        self._session_log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).isoformat()
        md_path = self._session_log_dir / f"{session_id}.md"
        md_path.write_text(
            f"# Session Log\n\n**Session ID:** {session_id}\n**Date:** {ts}\n\n---\n\n{content}\n",
            encoding="utf-8",
        )
        log_id = db.log_session_summary(session_id, content)
        logger.info("Session log saved: %s (db id=%d)", md_path, log_id)
