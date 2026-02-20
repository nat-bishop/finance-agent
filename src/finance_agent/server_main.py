"""Entry point for the WebSocket agent server."""

from __future__ import annotations

import asyncio

from .config import load_configs
from .logging_config import setup_logging
from .server import AgentServer


def main() -> None:
    agent_config, credentials, trading_config = load_configs()
    setup_logging(console=True)
    server = AgentServer(agent_config, trading_config, credentials)
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
