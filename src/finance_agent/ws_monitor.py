"""WebSocket fill monitors for Kalshi and Polymarket US.

Provides async fill detection for the leg-in execution strategy.
Each monitor connects to the exchange's private WebSocket, subscribes
to order/fill events, and waits for a specific order_id to fill.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
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
            with open(self._credentials.kalshi_private_key_path) as f:
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


class PolymarketFillMonitor:
    """Monitor Polymarket US order fills via WebSocket.

    Endpoint: wss://api.polymarket.us/v1/ws/private
    Auth: Ed25519 signature (X-PM-Access-Key, X-PM-Timestamp, X-PM-Signature)
    Channel: SUBSCRIPTION_TYPE_ORDER
    """

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        self._credentials = credentials
        self._config = config
        self._ws: Any = None
        self._connected = False

    def _ws_url(self) -> str:
        return "wss://api.polymarket.us/v1/ws/private"

    def _auth_headers(self) -> dict[str, str]:
        """Build Ed25519 signed auth headers for WebSocket."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        ts = str(int(time.time() * 1000))
        message = ts + "GET" + "/v1/ws/private"

        # Load Ed25519 private key from secret
        secret_bytes = base64.b64decode(self._credentials.polymarket_secret_key)
        private_key = Ed25519PrivateKey.from_private_bytes(secret_bytes[:32])
        signature = private_key.sign(message.encode())

        return {
            "X-PM-Access-Key": self._credentials.polymarket_key_id,
            "X-PM-Timestamp": ts,
            "X-PM-Signature": base64.b64encode(signature).decode(),
        }

    async def connect(self, market_slug: str | None = None) -> None:
        """Establish WebSocket connection and subscribe to order updates."""
        headers = self._auth_headers()
        self._ws = await websockets.connect(self._ws_url(), additional_headers=headers)
        self._connected = True

        # Subscribe to order updates
        sub_msg: dict[str, Any] = {
            "subscribe": {
                "requestId": "fill-monitor-1",
                "subscriptionType": "SUBSCRIPTION_TYPE_ORDER",
            }
        }
        if market_slug:
            sub_msg["subscribe"]["marketSlugs"] = [market_slug]

        await self._ws.send(json.dumps(sub_msg))
        logger.info("Polymarket WS: connected and subscribed to orders")

    async def wait_for_fill(self, order_id: str, timeout_sec: float) -> dict[str, Any] | None:
        """Wait for a specific order to fill. Returns fill info or None on timeout."""
        if not self._ws or not self._connected:
            await self.connect()

        deadline = asyncio.get_event_loop().time() + timeout_sec
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.info("Polymarket WS: timeout waiting for fill on %s", order_id)
                return None

            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=remaining)
                msg = json.loads(raw)
            except TimeoutError:
                return None
            except Exception as e:
                logger.warning("Polymarket WS recv error: %s", e)
                return None

            # Check for order execution update
            update = msg.get("orderSubscriptionUpdate", {})
            execution = update.get("execution", {})
            exec_type = execution.get("type", "")

            if exec_type in ("EXECUTION_TYPE_FILL", "EXECUTION_TYPE_PARTIAL_FILL"):
                order_data = execution.get("order", {})
                exec_order_id = str(order_data.get("id", order_data.get("orderId", "")))
                if exec_order_id == order_id:
                    logger.info(
                        "Polymarket WS: fill received for %s (type=%s)", order_id, exec_type
                    )
                    return {
                        "order_id": order_id,
                        "fill_type": exec_type,
                        "fill_quantity": int(execution.get("lastShares", 0)),
                        "fill_price": execution.get("lastPx", {}).get("value"),
                        "trade_id": execution.get("tradeId"),
                    }

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._connected = False
            logger.info("Polymarket WS: disconnected")


class FillMonitor:
    """Unified fill monitor — dispatches to exchange-specific implementations."""

    def __init__(self, credentials: Credentials, config: TradingConfig) -> None:
        self._credentials = credentials
        self._config = config
        self._kalshi: KalshiFillMonitor | None = None
        self._polymarket: PolymarketFillMonitor | None = None

    async def wait_for_fill(
        self,
        exchange: str,
        order_id: str,
        timeout_sec: float,
        market_slug: str | None = None,
    ) -> dict[str, Any] | None:
        """Wait for a fill on the specified exchange. Returns fill info or None."""
        if exchange == "kalshi":
            if not self._kalshi:
                self._kalshi = KalshiFillMonitor(self._credentials, self._config)
                await self._kalshi.connect()
            return await self._kalshi.wait_for_fill(order_id, timeout_sec)
        elif exchange == "polymarket":
            if not self._polymarket:
                self._polymarket = PolymarketFillMonitor(self._credentials, self._config)
                await self._polymarket.connect(market_slug)
            return await self._polymarket.wait_for_fill(order_id, timeout_sec)
        else:
            raise ValueError(f"Unknown exchange: {exchange}")

    async def close(self) -> None:
        """Close all WebSocket connections."""
        if self._kalshi:
            await self._kalshi.close()
        if self._polymarket:
            await self._polymarket.close()
