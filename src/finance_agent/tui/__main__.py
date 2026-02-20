"""Local TUI entry point: python -m finance_agent.tui"""

from ..logging_config import setup_logging
from .app import FinanceApp


def main() -> None:
    setup_logging(console=False, log_file="tui.log")
    app = FinanceApp()
    app.run()


if __name__ == "__main__":
    main()
