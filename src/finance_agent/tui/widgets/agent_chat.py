"""Chat widget embedding the Claude agent REPL."""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Button, Input, RichLog

from ..messages import AgentCostUpdate, AgentResponseComplete

logger = logging.getLogger(__name__)

_THINKING_FRAMES = ["Working .", "Working ..", "Working ..."]


class AgentChat(Vertical):
    """Agent chat pane: RichLog for output + Input/buttons for user messages."""

    _streaming: reactive[bool] = reactive(False)

    def __init__(self, client: ClaudeSDKClient, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._tick_timer: Timer | None = None
        self._frame_idx: int = 0

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
        with Horizontal(id="chat-input-row"):
            yield Input(placeholder="Type a message...", id="chat-input")
            yield Button("Stop", id="stop-btn", variant="error")
            yield Button("Clear", id="clear-btn", variant="warning")

    # ── Reactive watcher ──────────────────────────────────────────

    def watch__streaming(self, streaming: bool) -> None:
        inp = self.query_one("#chat-input", Input)
        stop_btn = self.query_one("#stop-btn", Button)
        inp.disabled = streaming
        stop_btn.display = streaming
        if streaming:
            self._frame_idx = 0
            self._tick_timer = self.set_interval(0.5, self._tick_placeholder)
        else:
            if self._tick_timer:
                self._tick_timer.stop()
                self._tick_timer = None
            inp.placeholder = "Type a message..."
            inp.focus()

    def _tick_placeholder(self) -> None:
        inp = self.query_one("#chat-input", Input)
        inp.placeholder = _THINKING_FRAMES[self._frame_idx % len(_THINKING_FRAMES)]
        self._frame_idx += 1

    # ── Input handler ─────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]> {text}[/]")
        logger.info("User: %s", text)
        self.run_worker(self._send_and_stream(text), exclusive=True)

    # ── Button handlers ───────────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop-btn":
            event.stop()
            log = self.query_one("#chat-log", RichLog)
            log.write("[bold yellow]Interrupting agent...[/]")
            try:
                await self._client.interrupt()
            except Exception as exc:
                log.write(f"[bold red]Could not interrupt: {exc}[/]")

        elif event.button.id == "clear-btn":
            event.stop()
            await self.app.run_action("clear_chat")

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self, client: ClaudeSDKClient) -> None:
        """Reset chat state for a new session."""
        self._client = client
        self._streaming = False
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#chat-input", Input).clear()

    # ── Streaming ─────────────────────────────────────────────────

    async def _send_and_stream(self, message: str) -> None:
        self._streaming = True
        log = self.query_one("#chat-log", RichLog)
        try:
            await self._client.query(message)
            got_result = False
            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            logger.info("Agent: %s", block.text[:200])
                            try:
                                log.write(Markdown(block.text))
                            except Exception:
                                log.write(block.text)
                        elif isinstance(block, ToolUseBlock):
                            logger.info("Tool call: %s (id=%s)", block.name, block.id)
                            logger.debug("Tool input: %s", block.input)
                        elif isinstance(block, ToolResultBlock):
                            preview = str(block.content)[:200] if block.content else ""
                            if block.is_error:
                                logger.warning(
                                    "Tool error (id=%s): %s",
                                    block.tool_use_id,
                                    preview,
                                )
                            else:
                                logger.info(
                                    "Tool result (id=%s): %s",
                                    block.tool_use_id,
                                    preview,
                                )
                elif isinstance(msg, ResultMessage):
                    got_result = True
                    if msg.total_cost_usd is not None:
                        logger.info("Session cost: $%.4f", msg.total_cost_usd)
                        self.post_message(AgentCostUpdate(msg.total_cost_usd))
                    if msg.is_error:
                        logger.error("Agent result error: %s", msg.result)
                        log.write(f"[bold red]Error: {msg.result}[/]")
            if not got_result:
                log.write(
                    "[bold yellow]Warning: agent response ended without a result — try again.[/]"
                )
        except Exception as exc:
            logger.exception("Agent streaming error")
            log.write(f"[bold red]Agent error: {exc}[/]")
        finally:
            self._streaming = False
            self.post_message(AgentResponseComplete())
