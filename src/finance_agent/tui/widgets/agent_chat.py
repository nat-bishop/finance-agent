"""Chat widget embedding the Claude agent REPL."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)
from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog

from ..messages import AgentCostUpdate, AgentResponseComplete


class AgentChat(Vertical):
    """Agent chat pane: RichLog for output + Input for user messages."""

    def __init__(
        self,
        client: ClaudeSDKClient,
        startup_msg: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._startup_msg = startup_msg

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
        yield Input(placeholder="Type a message...", id="chat-input")

    async def on_mount(self) -> None:
        """Send BEGIN_SESSION on mount."""
        self.run_worker(self._send_and_stream(self._startup_msg, show_input=False))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]> {text}[/]")
        self.run_worker(self._send_and_stream(text), exclusive=True)

    async def _send_and_stream(self, message: str, *, show_input: bool = True) -> None:
        chat_input = self.query_one("#chat-input", Input)
        chat_input.disabled = True

        log = self.query_one("#chat-log", RichLog)
        try:
            await self._client.query(message)
            async for msg in self._client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            try:
                                log.write(Markdown(block.text))
                            except Exception:
                                log.write(block.text)
                elif isinstance(msg, ResultMessage):
                    if msg.total_cost_usd is not None:
                        self.post_message(AgentCostUpdate(msg.total_cost_usd))
                    if msg.is_error:
                        log.write(f"[bold red]Error: {msg.result}[/]")
        except Exception as exc:
            log.write(f"[bold red]Agent error: {exc}[/]")
        finally:
            chat_input.disabled = False
            if show_input:
                chat_input.focus()
            self.post_message(AgentResponseComplete())
