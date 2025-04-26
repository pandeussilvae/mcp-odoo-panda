import asyncio
import json
import logging
from typing import Dict, Any, Set, Optional, Callable
import websockets
from websockets.exceptions import WebSocketException
from odoo_mcp.error_handling.exceptions import OdooMCPError, NetworkError, AuthError

logger = logging.getLogger(__name__)

class OdooBusHandler:
    """
    Handles real-time updates from Odoo's bus system.
    """
    def __init__(self, config: Dict[str, Any], notify_callback: Callable[[str, Dict[str, Any]], None]):
        """
        Initialize the Odoo bus handler.

        Args:
            config: Server configuration dictionary
            notify_callback: Callback function to notify about updates
        """
        self.config = config
        self.notify_callback = notify_callback
        self.ws_url = f"ws://{config['odoo_url'].replace('http://', '')}/websocket"
        self.db = config['database']
        self.uid = config.get('uid')
        self.password = config.get('password')
        self.channels: Set[str] = set()
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._reconnect_delay = 5  # Initial delay in seconds
        self._max_reconnect_delay = 60  # Maximum delay in seconds
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10

    async def start(self):
        """Start the bus handler."""
        if self._running:
            logger.warning("Bus handler already running")
            return

        logger.info("Starting Odoo bus handler...")
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Odoo bus handler started")

    async def stop(self):
        """Stop the bus handler."""
        if not self._running:
            logger.warning("Bus handler not running")
            return

        logger.info("Stopping Odoo bus handler...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {e}")
            self.websocket = None

        logger.info("Odoo bus handler stopped")

    async def subscribe(self, channel: str):
        """Subscribe to a channel."""
        if not channel.startswith("odoo://"):
            raise OdooMCPError(f"Invalid channel format: {channel}")

        if channel in self.channels:
            logger.warning(f"Already subscribed to channel: {channel}")
            return

        logger.info(f"Subscribing to channel: {channel}")
        self.channels.add(channel)
        if self.websocket and self.websocket.open:
            try:
                await self._send_subscribe(channel)
                logger.info(f"Successfully subscribed to channel: {channel}")
            except Exception as e:
                logger.error(f"Failed to subscribe to channel {channel}: {e}")
                self.channels.remove(channel)
                raise NetworkError(f"Failed to subscribe to channel: {e}")

    async def unsubscribe(self, channel: str):
        """Unsubscribe from a channel."""
        if not channel.startswith("odoo://"):
            raise OdooMCPError(f"Invalid channel format: {channel}")

        if channel not in self.channels:
            logger.warning(f"Not subscribed to channel: {channel}")
            return

        logger.info(f"Unsubscribing from channel: {channel}")
        self.channels.remove(channel)
        if self.websocket and self.websocket.open:
            try:
                await self._send_unsubscribe(channel)
                logger.info(f"Successfully unsubscribed from channel: {channel}")
            except Exception as e:
                logger.error(f"Failed to unsubscribe from channel {channel}: {e}")
                raise NetworkError(f"Failed to unsubscribe from channel: {e}")

    async def _run(self):
        """Main bus handler loop."""
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self.websocket = websocket
                    self._reconnect_attempts = 0
                    self._reconnect_delay = 5
                    logger.info("Connected to Odoo bus")

                    # Authenticate
                    await self._authenticate()

                    # Resubscribe to channels
                    for channel in self.channels:
                        try:
                            await self._send_subscribe(channel)
                            logger.info(f"Resubscribed to channel: {channel}")
                        except Exception as e:
                            logger.error(f"Failed to resubscribe to channel {channel}: {e}")

                    # Listen for messages
                    while self._running:
                        try:
                            message = await websocket.recv()
                            await self._handle_message(message)
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("WebSocket connection closed")
                            break
                        except Exception as e:
                            logger.exception(f"Error handling message: {e}")

            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error in bus handler: {e}")

            if self._running:
                self._reconnect_attempts += 1
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    logger.error("Maximum reconnection attempts reached")
                    self._running = False
                    break

                delay = min(self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)), self._max_reconnect_delay)
                logger.info(f"Reconnecting to Odoo bus in {delay} seconds... (attempt {self._reconnect_attempts})")
                await asyncio.sleep(delay)

    async def _authenticate(self):
        """Authenticate with the Odoo bus."""
        if not self.websocket:
            raise RuntimeError("WebSocket not connected")

        if not self.uid or not self.password:
            raise AuthError("Missing authentication credentials")

        auth_message = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "db": self.db,
                "login": self.uid,
                "password": self.password
            }
        }

        try:
            await self.websocket.send(json.dumps(auth_message))
            response = await self.websocket.recv()
            response_data = json.loads(response)

            if "error" in response_data:
                error_msg = response_data["error"].get("message", "Unknown error")
                logger.error(f"Authentication failed: {error_msg}")
                raise AuthError(f"Authentication failed: {error_msg}")

            logger.info("Successfully authenticated with Odoo bus")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode authentication response: {e}")
            raise NetworkError("Invalid authentication response")
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise AuthError(f"Authentication failed: {e}")

    async def _send_subscribe(self, channel: str):
        """Send subscribe message."""
        if not self.websocket:
            raise NetworkError("WebSocket not connected")

        subscribe_message = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "channel": channel,
                "action": "subscribe"
            }
        }

        try:
            await self.websocket.send(json.dumps(subscribe_message))
            response = await self.websocket.recv()
            response_data = json.loads(response)

            if "error" in response_data:
                error_msg = response_data["error"].get("message", "Unknown error")
                logger.error(f"Subscribe failed: {error_msg}")
                raise NetworkError(f"Subscribe failed: {error_msg}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode subscribe response: {e}")
            raise NetworkError("Invalid subscribe response")
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            raise NetworkError(f"Subscribe failed: {e}")

    async def _send_unsubscribe(self, channel: str):
        """Send unsubscribe message."""
        if not self.websocket:
            raise NetworkError("WebSocket not connected")

        unsubscribe_message = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "channel": channel,
                "action": "unsubscribe"
            }
        }

        try:
            await self.websocket.send(json.dumps(unsubscribe_message))
            response = await self.websocket.recv()
            response_data = json.loads(response)

            if "error" in response_data:
                error_msg = response_data["error"].get("message", "Unknown error")
                logger.error(f"Unsubscribe failed: {error_msg}")
                raise NetworkError(f"Unsubscribe failed: {error_msg}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode unsubscribe response: {e}")
            raise NetworkError("Invalid unsubscribe response")
        except Exception as e:
            logger.error(f"Unsubscribe error: {e}")
            raise NetworkError(f"Unsubscribe failed: {e}")

    async def _handle_message(self, message: str):
        """Handle incoming bus message."""
        try:
            data = json.loads(message)
            if "method" in data and data["method"] == "notification":
                channel = data["params"].get("channel")
                message_data = data["params"].get("message", {})
                
                if not channel:
                    logger.warning("Received notification without channel")
                    return

                # Convert Odoo bus message to MCP notification
                if channel.startswith("odoo://"):
                    try:
                        self.notify_callback(channel, message_data)
                        logger.debug(f"Processed notification for channel {channel}")
                    except Exception as e:
                        logger.error(f"Error processing notification for channel {channel}: {e}")
                else:
                    logger.debug(f"Ignoring notification for non-Odoo channel: {channel}")

        except json.JSONDecodeError:
            logger.error(f"Failed to decode message: {message}")
        except Exception as e:
            logger.exception(f"Error handling message: {e}") 