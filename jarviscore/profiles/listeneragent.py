"""
ListenerAgent - Agent profile for API-first services with secondary P2P.

For agents where HTTP API is primary and P2P listening is background
functionality. Abstracts away the message loop - developers just
implement handlers.

Example:
    class MyAPIAgent(ListenerAgent):
        role = "api_processor"
        capabilities = ["data_processing"]

        async def on_peer_request(self, msg):
            result = await self.process(msg.data)
            return {"status": "success", "result": result}

        async def on_peer_notify(self, msg):
            await self.log_event(msg.data)
"""
from abc import abstractmethod
from typing import Any, Optional, Dict
import asyncio
import logging

from .customagent import CustomAgent

logger = logging.getLogger(__name__)


class ListenerAgent(CustomAgent):
    """
    Agent that listens for peer messages without requiring a custom run() loop.

    Designed for API-first agents where:
    - The HTTP server (FastAPI, etc.) is the primary interface
    - P2P mesh participation is secondary/background functionality
    - You just want to handle incoming peer messages without loop boilerplate

    Instead of writing a run() loop, implement message handlers:
    - on_peer_request(msg) - Handle request-response messages (return value sent back)
    - on_peer_notify(msg) - Handle fire-and-forget notifications

    Configuration Attributes:
        listen_timeout: Seconds to wait for messages before checking shutdown (default: 1.0)
        auto_respond: Automatically send on_peer_request return value as response (default: True)

    Example - Basic Usage:
        class MyAPIAgent(ListenerAgent):
            role = "api_processor"
            capabilities = ["processing"]

            async def on_peer_request(self, msg):
                # Handle incoming requests from other agents
                result = await self.process(msg.data)
                return {"status": "success", "result": result}

            async def on_peer_notify(self, msg):
                # Handle fire-and-forget notifications
                await self.log_event(msg.data)

    Example - With FastAPI:
        from fastapi import FastAPI
        from jarviscore.integrations.fastapi import JarvisLifespan
        from jarviscore.profiles import ListenerAgent

        class ProcessorAgent(ListenerAgent):
            role = "processor"
            capabilities = ["data_processing"]

            async def on_peer_request(self, msg):
                if msg.data.get("action") == "process":
                    return {"result": await self.process(msg.data["payload"])}
                return {"error": "unknown action"}

        agent = ProcessorAgent()
        app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p"))

        @app.post("/process")
        async def process_endpoint(data: dict, request: Request):
            # HTTP endpoint - primary interface
            agent = request.app.state.jarvis_agents["processor"]
            return await agent.process(data)
    """

    # Configuration - can be overridden in subclasses
    listen_timeout: float = 1.0  # Seconds to wait for messages
    auto_respond: bool = True    # Automatically send response for requests

    async def run(self):
        """
        Default listener loop - handles peer messages automatically.

        Runs in background, dispatches incoming messages to:
        - on_peer_request() for request-response messages
        - on_peer_notify() for fire-and-forget notifications

        You typically don't need to override this. Just implement the handlers.
        """
        self._logger.info(f"[{self.role}] Listener loop started")

        while not self.shutdown_requested:
            try:
                # Wait for incoming message with timeout
                # Timeout allows periodic shutdown_requested checks
                msg = await self.peers.receive(timeout=self.listen_timeout)

                if msg is None:
                    # Timeout - no message, continue loop to check shutdown
                    continue

                # Dispatch to appropriate handler
                await self._dispatch_message(msg)

            except asyncio.CancelledError:
                self._logger.debug(f"[{self.role}] Listener loop cancelled")
                raise
            except Exception as e:
                self._logger.error(f"[{self.role}] Listener loop error: {e}")
                await self.on_error(e, None)

        self._logger.info(f"[{self.role}] Listener loop stopped")

    async def _dispatch_message(self, msg):
        """
        Dispatch message to appropriate handler based on message type.

        Handles:
        - REQUEST messages: calls on_peer_request, sends response if auto_respond=True
        - NOTIFY messages: calls on_peer_notify
        """
        from jarviscore.p2p.messages import MessageType

        try:
            # Check if this is a request (expects response)
            is_request = (
                msg.type == MessageType.REQUEST or
                getattr(msg, 'is_request', False) or
                msg.correlation_id is not None
            )

            if is_request:
                # Request-response: call handler, optionally send response
                response = await self.on_peer_request(msg)

                if self.auto_respond and response is not None:
                    await self.peers.respond(msg, response)
                    self._logger.debug(
                        f"[{self.role}] Sent response to {msg.sender}"
                    )
            else:
                # Notification: fire-and-forget
                await self.on_peer_notify(msg)

        except Exception as e:
            self._logger.error(
                f"[{self.role}] Error handling message from {msg.sender}: {e}"
            )
            await self.on_error(e, msg)

    # ─────────────────────────────────────────────────────────────────
    # Override these methods in your agent
    # ─────────────────────────────────────────────────────────────────

    @abstractmethod
    async def on_peer_request(self, msg) -> Any:
        """
        Handle incoming peer request.

        Override this to process request-response messages from other agents.
        The return value is automatically sent as response (if auto_respond=True).

        Args:
            msg: IncomingMessage with:
                - msg.sender: Sender agent ID or role
                - msg.data: Request payload (dict)
                - msg.correlation_id: For response matching (handled automatically)

        Returns:
            Response data (dict) to send back to the requester.
            Return None to skip sending a response.

        Example:
            async def on_peer_request(self, msg):
                action = msg.data.get("action")

                if action == "analyze":
                    result = await self.analyze(msg.data["payload"])
                    return {"status": "success", "result": result}

                elif action == "status":
                    return {"status": "ok", "queue_size": self.queue_size}

                return {"status": "error", "message": f"Unknown action: {action}"}
        """
        pass

    async def on_peer_notify(self, msg) -> None:
        """
        Handle incoming peer notification.

        Override this to process fire-and-forget messages from other agents.
        No response is expected or sent.

        Args:
            msg: IncomingMessage with:
                - msg.sender: Sender agent ID or role
                - msg.data: Notification payload (dict)

        Example:
            async def on_peer_notify(self, msg):
                event = msg.data.get("event")

                if event == "task_complete":
                    await self.update_dashboard(msg.data)
                    self._logger.info(f"Task completed by {msg.sender}")

                elif event == "peer_joined":
                    self._logger.info(f"New peer in mesh: {msg.data.get('role')}")
        """
        # Default: log and ignore
        self._logger.debug(
            f"[{self.role}] Received notify from {msg.sender}: "
            f"{list(msg.data.keys()) if isinstance(msg.data, dict) else 'data'}"
        )

    async def on_error(self, error: Exception, msg=None) -> None:
        """
        Handle errors during message processing.

        Override to customize error handling (logging, alerting, metrics, etc.)
        Default implementation logs the error and continues processing.

        Args:
            error: The exception that occurred
            msg: The message being processed when error occurred (may be None)

        Example:
            async def on_error(self, error, msg):
                # Log with context
                self._logger.error(
                    f"Error processing message: {error}",
                    extra={"sender": msg.sender if msg else None}
                )

                # Send to error tracking service
                await self.error_tracker.capture(error, context={"msg": msg})

                # Optionally notify the sender of failure
                if msg and msg.correlation_id:
                    await self.peers.respond(msg, {
                        "status": "error",
                        "error": str(error)
                    })
        """
        if msg:
            self._logger.error(
                f"[{self.role}] Error processing message from {msg.sender}: {error}"
            )
        else:
            self._logger.error(f"[{self.role}] Error in listener loop: {error}")

    # ─────────────────────────────────────────────────────────────────
    # Workflow compatibility
    # ─────────────────────────────────────────────────────────────────

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task (for workflow/distributed modes).

        Delegates to on_peer_request for consistency, allowing the same
        agent to work in both P2P and workflow modes.

        Args:
            task: Task specification dict

        Returns:
            Result dict with status and output
        """
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        # Create a synthetic message to pass to the handler
        synthetic_msg = IncomingMessage(
            sender="workflow",
            sender_node="local",
            type=MessageType.REQUEST,
            data=task,
            correlation_id=None,
            timestamp=0
        )

        result = await self.on_peer_request(synthetic_msg)
        return {"status": "success", "output": result}
