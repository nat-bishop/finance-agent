"""WebSocket fill monitor for Kalshi.

Provides async fill detection for the leg-in execution strategy.
Connects to Kalshi's private WebSocket, subscribes to order/fill events,
and waits for a specific order_id to fill.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import websockets

from .config import Credentials, TradingConfig

logger = logging.getLogger(__name__)


class KalshiFillMonitor:
    """Monitor Kalshi order fills via WebSocket.

    Endpoint: wss://api.elections.kalshi.com/trade-api/ws/v2
    Auth: RSA-PSS signed headers (KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP)
    Channel: "fill"
    """

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        self._credentials = credentials
        self._config = config
        self._ws: Any = None
        self._connected = False

    def _ws_url(self) -> str:
        return f"{self._config.kalshi_base_url}/trade-api/ws/v2".replace("https://", "wss://")

    def _auth_headers(self) -> dict[str, str]:
        """Build RSA-PSS signed auth headers for WebSocket."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        ts = str(int(time.time() * 1000))
        message = ts + "GET" + "/trade-api/ws/v2"

        pem = self._credentials.kalshi_private_key
        if not pem:
            with Path(self._credentials.kalshi_private_key_path).open() as f:
                pem = f.read()
        else:
            pem = pem.replace("\\n", "\n")

        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise TypeError("Kalshi requires an RSA private key")
        signature = private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": self._credentials.kalshi_api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        }

    async def connect(self) -> None:
        """Establish WebSocket connection and subscribe to fill channel."""
        headers = self._auth_headers()
        self._ws = await websockets.connect(self._ws_url(), additional_headers=headers)
        self._connected = True

        # Subscribe to fill channel
        await self._ws.send(
            json.dumps(
                {
                    "id": 1,
                    "cmd": "subscribe",
                    "params": {"channels": ["fill"]},
                }
            )
        )
        logger.info("Kalshi WS: connected and subscribed to fills")

    async def wait_for_fill(self, order_id: str, timeout_sec: float) -> dict[str, Any] | None:
        """Wait for a specific order to fill. Returns fill info or None on timeout."""
        if not self._ws or not self._connected:
            await self.connect()

        deadline = asyncio.get_event_loop().time() + timeout_sec
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info("Kalshi WS: timeout waiting for fill on %s", order_id)
                return None

            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
                msg = json.loads(raw)
            except TimeoutError:
                return None
            except Exception as e:
                logger.warning("Kalshi WS recv error: %s", e)
                return None

            # Check if this message is a fill for our order
            msg_type = msg.get("type", "")
            if msg_type == "fill" or "fill" in str(msg.get("channel", "")):
                fill_data = msg.get("msg", msg.get("data", msg))
                if str(fill_data.get("order_id", "")) == order_id:
                    logger.info("Kalshi WS: fill received for %s", order_id)
                    return fill_data

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._connected = False
            logger.info("Kalshi WS: disconnected")


class FillMonitor:
    """Unified fill monitor — dispatches to exchange-specific implementations."""

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        self._credentials = credentials
        self._config = config
        self._kalshi: KalshiFillMonitor | None = None

    async def wait_for_fill(
        self,
        exchange: str,
        order_id: str,
        timeout_sec: float,
        market_slug: str | None = None,
    ) -> dict[str, Any] | None:
        """Wait for a fill on the specified exchange. Returns fill info or None."""
        if exchange != "kalshi":
            raise ValueError(f"Unknown exchange: {exchange}")
        if not self._kalshi:
            self._kalshi = KalshiFillMonitor(self._credentials, self._config)
            await self._kalshi.connect()
        return await self._kalshi.wait_for_fill(order_id, timeout_sec)

    async def close(self) -> None:
        """Close all WebSocket connections."""
        if self._kalshi:
            await self._kalshi.close()
