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
from textual.containers import Vertical
from textual.widgets import Input, RichLog

from ..messages import AgentCostUpdate, AgentResponseComplete

logger = logging.getLogger(__name__)


class AgentChat(Vertical):
    """Agent chat pane: RichLog for output + Input for user messages."""

    def __init__(
        self,
        client: ClaudeSDKClient,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
        yield Input(placeholder="Type a message...", id="chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]> {text}[/]")
        logger.info("User: %s", text)
        self.run_worker(self._send_and_stream(text), exclusive=True)

    def reset(self, client: ClaudeSDKClient) -> None:
        """Reset chat state for a new session."""
        self._client = client
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#chat-input", Input).clear()

    async def _send_and_stream(self, message: str) -> None:
        chat_input = self.query_one("#chat-input", Input)
        chat_input.disabled = True

        log = self.query_one("#chat-log", RichLog)
        try:
            await self._client.query(message)
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
                    if msg.total_cost_usd is not None:
                        logger.info("Session cost: $%.4f", msg.total_cost_usd)
                        self.post_message(AgentCostUpdate(msg.total_cost_usd))
                    if msg.is_error:
                        logger.error("Agent result error: %s", msg.result)
                        log.write(f"[bold red]Error: {msg.result}[/]")
        except Exception as exc:
            logger.exception("Agent streaming error")
            log.write(f"[bold red]Agent error: {exc}[/]")
        finally:
            chat_input.disabled = False
            chat_input.focus()
            self.post_message(AgentResponseComplete())
