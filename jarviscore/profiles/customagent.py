"""
CustomAgent - User-controlled execution profile with P2P message handling.

Unified profile for building agents that:
- Handle P2P mesh communication (requests, notifications)
- Execute workflow tasks
- Integrate with HTTP APIs (FastAPI, Flask, etc.)

Example - Basic P2P Agent:
    class AnalystAgent(CustomAgent):
        role = "analyst"
        capabilities = ["analysis"]

        async def on_peer_request(self, msg):
            result = await self.analyze(msg.data)
            return {"status": "success", "result": result}

Example - With FastAPI:
    from fastapi import FastAPI
    from jarviscore.integrations.fastapi import JarvisLifespan

    class ProcessorAgent(CustomAgent):
        role = "processor"
        capabilities = ["processing"]

        async def on_peer_request(self, msg):
            return {"result": await self.process(msg.data)}

    app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))
"""
from typing import Dict, Any, Optional
import asyncio
import logging

from jarviscore.core.profile import Profile

logger = logging.getLogger(__name__)


class CustomAgent(Profile):
    """
    User-controlled agent profile with P2P message handling.

    For P2P messaging, implement these handlers:
        on_peer_request(msg) - Handle requests, return response
        on_peer_notify(msg)  - Handle notifications (fire-and-forget)
        on_error(error, msg) - Handle errors

    For workflow execution:
        execute_task(task)   - Handle workflow tasks directly
        (defaults to delegating to on_peer_request)

    Configuration:
        listen_timeout: Seconds to wait for messages (default: 1.0)
        auto_respond: Auto-send on_peer_request return value (default: True)

    Example - P2P Agent:
        class AnalystAgent(CustomAgent):
            role = "analyst"
            capabilities = ["analysis"]

            async def on_peer_request(self, msg):
                result = await self.analyze(msg.data)
                return {"status": "success", "result": result}

    Example - With LangChain:
        class LangChainAgent(CustomAgent):
            role = "assistant"
            capabilities = ["chat"]

            async def setup(self):
                await super().setup()
                from langchain.agents import Agent
                self.lc_agent = Agent(...)

            async def on_peer_request(self, msg):
                result = await self.lc_agent.run(msg.data["query"])
                return {"status": "success", "output": result}

    Example - With MCP:
        class MCPAgent(CustomAgent):
            role = "tool_user"
            capabilities = ["mcp_tools"]

            async def setup(self):
                await super().setup()
                from mcp import Client
                self.mcp = Client("stdio://./server.py")
                await self.mcp.connect()

            async def on_peer_request(self, msg):
                result = await self.mcp.call_tool("my_tool", msg.data)
                return {"status": "success", "data": result}

    Example - With FastAPI:
        from fastapi import FastAPI
        from jarviscore.integrations.fastapi import JarvisLifespan

        class ProcessorAgent(CustomAgent):
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

    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(agent_id)

    async def setup(self):
        """
        Initialize agent resources. Override to add custom setup.

        Example:
            async def setup(self):
                await super().setup()
                # Initialize your framework
                from langchain.agents import Agent
                self.agent = Agent(...)
        """
        await super().setup()
        self._logger.info(f"CustomAgent setup: {self.agent_id}")

    # ─────────────────────────────────────────────────────────────────
    # P2P Message Handling
    # ─────────────────────────────────────────────────────────────────

    async def run(self):
        """
        Listener loop - receives and dispatches P2P messages.

        Runs automatically in P2P mode. Dispatches messages to:
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
        - RESPONSE messages: ignored (handled by _deliver_message resolving futures)
        """
        from jarviscore.p2p.messages import MessageType

        try:
            # Skip RESPONSE messages - they should be handled by pending request futures
            if msg.type == MessageType.RESPONSE:
                self._logger.debug(
                    f"[{self.role}] Ignoring orphaned RESPONSE from {msg.sender} (no pending request)"
                )
                return
            
            # Check if this is a request (expects response)
            is_request = (
                msg.type == MessageType.REQUEST or
                getattr(msg, 'is_request', False)
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
    # Message Handlers - Override in your agent
    # ─────────────────────────────────────────────────────────────────

    async def on_peer_request(self, msg) -> Any:
        """
        Handle incoming peer request.

        Override to process request-response messages from other agents.
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
        return None

    async def on_peer_notify(self, msg) -> None:
        """
        Handle incoming peer notification.

        Override to process fire-and-forget messages from other agents.
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
    # Workflow Compatibility
    # ─────────────────────────────────────────────────────────────────

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task (for workflow/distributed modes).

        Default: Delegates to on_peer_request via synthetic message.
        Override for custom workflow logic.

        Args:
            task: Task specification dict

        Returns:
            Result dict with status and output

        Raises:
            NotImplementedError: If on_peer_request returns None and
                                 execute_task is not overridden
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

        if result is not None:
            return {"status": "success", "output": result}

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement on_peer_request() or execute_task()\n\n"
            f"Example:\n"
            f"    async def on_peer_request(self, msg):\n"
            f"        result = await self.process(msg.data)\n"
            f"        return {{'status': 'success', 'result': result}}\n"
        )
