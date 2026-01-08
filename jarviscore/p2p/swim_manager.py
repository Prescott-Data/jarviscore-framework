"""
SWIM Thread Manager for JarvisCore Framework
Runs SWIM protocol in dedicated thread to prevent GIL blocking from CPU-bound workflow operations.

Adapted from integration-agent/src/swim_thread_manager.py
- Updated imports to use jarviscore.config
- Kept core functionality identical
"""
import asyncio
import logging
import threading
import time
from typing import Optional

from swim.transport.hybrid import HybridTransport
from swim.protocol.node import Node
from swim.config import get_config as get_swim_config, validate_config as validate_swim_config
from swim.events.dispatcher import EventDispatcher
from swim.integration.agent import ZMQAgentIntegration
from swim.main import SWIMZMQBridge, parse_address as swim_parse_address

logger = logging.getLogger(__name__)


class SWIMThreadManager:
    """Manages SWIM node in a dedicated thread with its own event loop."""

    def __init__(self, config: Optional[dict] = None):
        """
        Initialize SWIM Thread Manager.

        Args:
            config: Configuration dictionary (uses defaults if not provided)
        """
        self.config = config or {}
        self.swim_loop: Optional[asyncio.AbstractEventLoop] = None
        self.swim_thread: Optional[threading.Thread] = None
        self.swim_node = None
        self.zmq_agent = None
        self.swim_zmq_bridge = None
        self.event_dispatcher = None
        self.bind_addr = None  # Store bind address for node_id access
        self._started = False
        self._initialized = threading.Event()
        self._shutdown_event = threading.Event()
        self._init_error: Optional[str] = None

    def start_swim_in_thread_simple(self):
        """
        Start SWIM in dedicated thread using configuration.
        """
        if self._started:
            logger.warning("SWIM thread already started")
            return

        logger.info("Starting SWIM in dedicated thread...")
        self.swim_thread = threading.Thread(
            target=self._run_swim_loop,
            daemon=True,
            name="SWIM-Protocol-Thread"
        )
        self.swim_thread.start()
        self._started = True
        logger.info("SWIM thread started")

    def _run_swim_loop(self):
        """Run SWIM in dedicated event loop (runs in thread)."""
        try:
            # Create new event loop for this thread
            self.swim_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.swim_loop)

            logger.info("SWIM thread event loop created")

            # Initialize SWIM
            self.swim_loop.run_until_complete(self._init_swim())

            if not self.swim_node:
                logger.error("SWIM initialization failed in thread")
                self._init_error = "Failed to create SWIM node"
                self._initialized.set()
                return

            logger.info("✅ SWIM initialized successfully in dedicated thread")
            logger.info("   SWIM will never be blocked by workflow execution!")

            # Signal that initialization is complete
            self._initialized.set()

            # Run event loop until shutdown
            self._run_until_shutdown()

        except Exception as e:
            logger.error(f"Error in SWIM thread: {e}", exc_info=True)
            self._init_error = str(e)
            self._initialized.set()
        finally:
            if self.swim_loop:
                try:
                    self.swim_loop.close()
                except Exception as e:
                    logger.error(f"Error closing SWIM loop: {e}")

    async def _init_swim(self):
        """Initialize SWIM components."""
        try:
            # Get configuration with defaults
            bind_host = self.config.get('bind_host', '127.0.0.1')
            bind_port = self.config.get('bind_port', 7946)
            node_name = self.config.get('node_name', 'jarviscore-node')
            seed_nodes = self.config.get('seed_nodes', '')
            transport_type = self.config.get('transport_type', 'hybrid')
            zmq_port_offset = self.config.get('zmq_port_offset', 1000)

            # Parse bind address
            self.bind_addr = swim_parse_address(f"{bind_host}:{bind_port}")
            logger.info(f"SWIM bind address: {self.bind_addr}")

            # Parse seed nodes
            seed_addrs = []
            if seed_nodes:
                for seed in seed_nodes.split(','):
                    if seed.strip():
                        seed_addrs.append(swim_parse_address(seed.strip()))
            logger.info(f"SWIM seed nodes: {seed_addrs}")

            # Get SWIM config
            swim_config = get_swim_config()
            swim_config.update({
                "NODE_NAME": node_name,
                "ZMQ_ENABLED": True,
                "SEND_ON_JOIN": True,
                "ZMQ_PORT_OFFSET": zmq_port_offset,
                "TRANSPORT_TYPE": transport_type,
                "STABILITY_TIMEOUT_SECONDS": 3.0
            })

            # Validate config
            errors = validate_swim_config(swim_config)
            if errors:
                logger.error(f"SWIM config validation errors: {errors}")
                return

            # Create transport
            transport = HybridTransport(
                udp_max_size=swim_config.get("UDP_MAX_SIZE", 1400),
                tcp_buffer_size=swim_config.get("TCP_BUFFER_SIZE", 65536),
                tcp_max_connections=swim_config.get("TCP_MAX_CONNECTIONS", 128)
            )

            # Create event dispatcher
            self.event_dispatcher = EventDispatcher(
                max_history_size=swim_config.get("EVENT_HISTORY", 1000),
                enable_history=swim_config.get("EVENTS_ENABLED", True)
            )

            # Create SWIM node
            logger.info("Creating SWIM node in dedicated thread...")
            self.swim_node = await Node.create(
                bind_addr=self.bind_addr,
                transport=transport,
                seed_addrs=seed_addrs,
                config=swim_config,
                event_dispatcher=self.event_dispatcher,
                validate_ports=True
            )

            if not self.swim_node:
                logger.error("Failed to create SWIM node")
                return

            logger.info(f"SWIM node created at {self.bind_addr}")

            # Setup ZMQ integration
            zmq_port = self.bind_addr[1] + swim_config.get("ZMQ_PORT_OFFSET", zmq_port_offset)
            zmq_addr = f"{self.bind_addr[0]}:{zmq_port}"
            node_id = f"{self.bind_addr[0]}:{self.bind_addr[1]}"
            logger.info(f"Setting up ZMQ integration at {zmq_addr}")

            self.zmq_agent = ZMQAgentIntegration(
                node_id=node_id,
                bind_address=zmq_addr,
                event_dispatcher=self.event_dispatcher,
                config=swim_config
            )

            # Start ZMQ agent
            logger.info("Starting ZMQ agent...")
            await self.zmq_agent.start()
            logger.info("ZMQ agent started successfully")

            # Setup SWIM-ZMQ Bridge
            logger.info("Setting up SWIM-ZMQ Bridge...")
            self.swim_zmq_bridge = SWIMZMQBridge(self.swim_node, self.zmq_agent, swim_config)
            await self.swim_zmq_bridge.start()
            logger.info("SWIM-ZMQ Bridge started successfully")

            # Start the SWIM protocol
            logger.info("Starting SWIM protocol...")
            await self.swim_node.start()
            logger.info("SWIM node started successfully")

        except Exception as e:
            logger.error(f"Error initializing SWIM: {e}", exc_info=True)
            raise

    def _run_until_shutdown(self):
        """Keep SWIM event loop running until shutdown requested."""
        while not self._shutdown_event.is_set():
            try:
                # Process events with timeout so we can check shutdown flag
                self.swim_loop.run_until_complete(asyncio.sleep(0.5))
            except Exception as e:
                logger.error(f"Error in SWIM event loop: {e}")

        logger.info("SWIM thread shutdown requested")

        # Cleanup SWIM components
        try:
            if self.swim_zmq_bridge and hasattr(self.swim_zmq_bridge, 'stop'):
                self.swim_loop.run_until_complete(self.swim_zmq_bridge.stop())
            if self.zmq_agent:
                self.swim_loop.run_until_complete(self.zmq_agent.stop())
            if self.swim_node:
                self.swim_loop.run_until_complete(self.swim_node.stop())
        except Exception as e:
            logger.error(f"Error during SWIM shutdown: {e}")

    def wait_for_init(self, timeout: float = 20.0) -> bool:
        """
        Wait for SWIM to initialize.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if initialized successfully, False if timeout or error
        """
        logger.info(f"Waiting for SWIM initialization (timeout: {timeout}s)...")

        if self._initialized.wait(timeout=timeout):
            if self._init_error:
                logger.error(f"SWIM initialization failed: {self._init_error}")
                return False
            if self.swim_node and self.zmq_agent:
                logger.info("SWIM initialization confirmed")
                return True
            else:
                logger.error("SWIM initialization incomplete")
                return False
        else:
            logger.error(f"SWIM initialization timeout after {timeout}s")
            return False

    def is_healthy(self) -> bool:
        """Check if SWIM thread is healthy."""
        return (
            self._started and
            self.swim_thread is not None and
            self.swim_thread.is_alive() and
            self.swim_node is not None and
            self.zmq_agent is not None
        )

    def get_status(self) -> dict:
        """Get SWIM thread status."""
        return {
            'started': self._started,
            'thread_alive': self.swim_thread.is_alive() if self.swim_thread else False,
            'swim_node': self.swim_node is not None,
            'zmq_agent': self.zmq_agent is not None,
            'bridge': self.swim_zmq_bridge is not None,
            'healthy': self.is_healthy()
        }

    def shutdown(self, timeout: float = 10.0):
        """Shutdown SWIM thread gracefully."""
        if not self._started:
            return

        logger.info("Shutting down SWIM thread...")
        self._shutdown_event.set()

        if self.swim_thread:
            self.swim_thread.join(timeout=timeout)
            if self.swim_thread.is_alive():
                logger.warning("SWIM thread did not exit cleanly")

        self._started = False
        logger.info("SWIM thread shutdown complete")
