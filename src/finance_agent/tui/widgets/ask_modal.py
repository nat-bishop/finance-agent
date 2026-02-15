"""Modal dialog for AskUserQuestion tool calls."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class AskModal(ModalScreen[dict[str, str] | None]):
    """Modal with question fields and option buttons."""

    def __init__(self, questions: list[dict]) -> None:
        super().__init__()
        self.questions = questions
        self._answers: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="ask-dialog"):
            for i, q in enumerate(self.questions):
                yield Label(
                    q.get("header", "Question"),
                    classes="question-header",
                )
                yield Label(q["question"])

                options = q.get("options", [])
                if options:
                    for j, opt in enumerate(options):
                        desc = opt.get("description", "")
                        label = opt["label"]
                        if desc:
                            label = f"{label} -- {desc}"
                        yield Button(
                            label,
                            id=f"opt-{i}-{j}",
                            classes="option-btn",
                            variant="default",
                        )
                    yield Input(
                        placeholder="Or type your own answer...",
                        id=f"input-{i}",
                    )
                else:
                    yield Input(
                        placeholder="Your answer...",
                        id=f"input-{i}",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if not btn_id.startswith("opt-"):
            return
        parts = btn_id.split("-")
        q_idx, opt_idx = int(parts[1]), int(parts[2])
        question_text = self.questions[q_idx]["question"]
        option_label = self.questions[q_idx]["options"][opt_idx]["label"]
        self._answers[question_text] = option_label

        # If all questions answered, dismiss
        if len(self._answers) == len(self.questions):
            self.dismiss(self._answers)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        input_id = event.input.id or ""
        if not input_id.startswith("input-"):
            return
        q_idx = int(input_id.split("-")[1])
        text = event.value.strip()
        if not text:
            return
        question_text = self.questions[q_idx]["question"]

        # Check if it's a number selecting an option
        options = self.questions[q_idx].get("options", [])
        try:
            idx = int(text) - 1
            if 0 <= idx < len(options):
                text = options[idx]["label"]
        except ValueError:
            pass

        self._answers[question_text] = text

        if len(self._answers) == len(self.questions):
            self.dismiss(self._answers)

    def key_escape(self) -> None:
        self.dismiss(None)
