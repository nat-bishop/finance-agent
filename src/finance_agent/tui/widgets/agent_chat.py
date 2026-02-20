"""Chat widget — renders agent output from WebSocket messages."""

from __future__ import annotations

import logging
from typing import Any

from rich.markdown import Markdown
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Button, RichLog, TextArea

from ..messages import (
    AgentResponseComplete,
    AgentResultReceived,
    AgentTextReceived,
    AgentToolResult,
    AgentToolUse,
)

logger = logging.getLogger(__name__)

_THINKING_FRAMES = ["Working .", "Working ..", "Working ..."]


class ChatInput(TextArea):
    """TextArea that submits on Enter and inserts newline on Shift+Enter."""

    class Submitted(Message):
        """Fired when the user presses Enter (without Shift)."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # Bare Enter submits the message
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
        elif event.key == "shift+enter":
            # Shift+Enter inserts a newline (TextArea only maps bare "enter")
            event.prevent_default()
            event.stop()
            self.insert("\n")
        else:
            await super()._on_key(event)


class AgentChat(Vertical):
    """Agent chat pane: RichLog for output + TextArea/buttons for user messages."""

    _streaming: reactive[bool] = reactive(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tick_timer: Timer | None = None
        self._frame_idx: int = 0
        self._pending_tools: dict[str, str] = {}  # tool_id -> display string

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
        with Horizontal(id="chat-input-row"):
            yield ChatInput(placeholder="Type a message...", id="chat-input", soft_wrap=True)
            yield Button("Stop", id="stop-btn", variant="error")
            yield Button("Clear", id="clear-btn", variant="warning")

    # ── Reactive watcher ──────────────────────────────────────────

    def watch__streaming(self, streaming: bool) -> None:
        inp = self.query_one("#chat-input", ChatInput)
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
        inp = self.query_one("#chat-input", ChatInput)
        inp.placeholder = _THINKING_FRAMES[self._frame_idx % len(_THINKING_FRAMES)]
        self._frame_idx += 1

    # ── Input handler ─────────────────────────────────────────────

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        text = event.text
        inp = self.query_one("#chat-input", ChatInput)
        inp.text = ""
        self.query_one("#chat-input-row").styles.height = 3
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]> {text}[/]")
        logger.info("User: %s", text)

        # Send via WebSocket through the app
        self._streaming = True
        self.run_worker(self._send_chat(text), exclusive=True)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Auto-grow the input row based on line count."""
        line_count = event.text_area.text.count("\n") + 1
        target = min(max(line_count + 2, 3), 10)
        self.query_one("#chat-input-row").styles.height = target

    async def _send_chat(self, text: str) -> None:
        """Send chat message via the app's WebSocket connection."""
        await self.app.send_ws({"type": "chat", "content": text})  # type: ignore[attr-defined]

    # ── Button handlers ───────────────────────────────────────────

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stop-btn":
            event.stop()
            log = self.query_one("#chat-log", RichLog)
            log.write("[bold yellow]Interrupting agent...[/]")
            await self.app.send_ws({"type": "interrupt"})  # type: ignore[attr-defined]

        elif event.button.id == "clear-btn":
            event.stop()
            await self.app.run_action("clear_chat")

    # ── WS message handlers (posted by app's WS listener) ────────

    def on_agent_text_received(self, event: AgentTextReceived) -> None:
        log = self.query_one("#chat-log", RichLog)
        logger.info("Agent: %s", event.content[:200])
        try:
            log.write(Markdown(event.content))
        except Exception:
            log.write(event.content)

    def on_agent_tool_use(self, event: AgentToolUse) -> None:
        display = self._format_tool_call(event.name, event.input_data)
        self._pending_tools[event.tool_id] = display
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[dim italic]  > {display}[/]")

    def on_agent_tool_result(self, event: AgentToolResult) -> None:
        display = self._pending_tools.pop(event.tool_id, "tool")
        preview = event.content[:120].replace("\n", " ").strip()
        if len(event.content) > 120:
            preview += "..."
        log = self.query_one("#chat-log", RichLog)
        if event.is_error:
            log.write(f"[dim red]  ! {display} error: {preview}[/]")
        else:
            log.write(f"[dim]  < {display}: {preview}[/]")

    @staticmethod
    def _format_tool_call(raw_name: str, input_data: dict[str, Any]) -> str:
        """Format tool name + key input param for display."""
        name = raw_name.split("__")[-1] if "__" in raw_name else raw_name
        if name == "Bash" and "command" in input_data:
            return f"Bash({input_data['command'][:80]})"
        if name in ("Read", "Write", "Edit") and "file_path" in input_data:
            return f"{name}({input_data['file_path']})"
        if name == "Glob" and "pattern" in input_data:
            return f"Glob({input_data['pattern']})"
        # MCP tools: show first string arg value
        for v in input_data.values():
            if isinstance(v, str) and v:
                return f"{name}({v[:60]})"
        return name

    def on_agent_result_received(self, event: AgentResultReceived) -> None:
        log = self.query_one("#chat-log", RichLog)
        self._streaming = False

        if event.total_cost_usd:
            logger.info("Session cost: $%.4f", event.total_cost_usd)
            from ..messages import AgentCostUpdate

            self.post_message(AgentCostUpdate(event.total_cost_usd))

        if event.is_error:
            log.write("[bold red]Agent returned an error[/]")

        self.post_message(AgentResponseComplete())

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset chat state for a new session."""
        self._streaming = False
        self._pending_tools.clear()
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#chat-input", ChatInput).text = ""
        self.query_one("#chat-input-row").styles.height = 3
