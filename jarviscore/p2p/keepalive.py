"""
P2P Keepalive Manager for maintaining active ZMQ connections in agent mesh.

Prevents idle connection closure by sending periodic keepalive messages
while intelligently suppressing when real workflow traffic exists.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states for connection health."""
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


@dataclass
class KeepaliveMetrics:
    """Metrics for P2P keepalive health monitoring."""
    keepalives_sent: int = 0
    keepalives_received: int = 0
    acks_received: int = 0
    timeouts: int = 0
    suppressed_count: int = 0
    last_successful_keepalive: float = 0.0
    last_keepalive_latency: float = 0.0
    circuit_breaker_events: int = 0


class P2PKeepaliveManager:
    """
    Manages P2P keepalive messages to prevent ZMQ connection idle closure.
    
    Features:
    - Periodic keepalive with configurable interval
    - Smart suppression when recent workflow traffic exists
    - Circuit breaker integration for adaptive behavior
    - Health metrics and observability
    - Bidirectional keepalive + ACK pattern
    """
    
    def __init__(
        self,
        agent_id: str,
        send_p2p_callback: Callable[[str, str, Dict[str, Any]], bool],
        broadcast_p2p_callback: Optional[Callable[[str, Dict[str, Any]], int]] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize P2P Keepalive Manager.
        
        Args:
            agent_id: Unique identifier for this agent
            send_p2p_callback: Function to send P2P message to specific peer
            broadcast_p2p_callback: Optional function to broadcast to all peers
            config: Configuration dictionary
        """
        self.agent_id = agent_id
        self.send_p2p_message = send_p2p_callback
        self.broadcast_p2p_message = broadcast_p2p_callback
        
        # Configuration with production defaults
        config = config or {}
        self.enabled = config.get('P2P_KEEPALIVE_ENABLED', True)
        self.interval = config.get('P2P_KEEPALIVE_INTERVAL', 90)  # 90s default
        self.timeout = config.get('P2P_KEEPALIVE_TIMEOUT', 10)  # 10s timeout
        self.activity_suppress_window = config.get('P2P_ACTIVITY_SUPPRESS_WINDOW', 60)  # 60s
        self.circuit_half_open_interval = config.get('P2P_CIRCUIT_HALF_OPEN_INTERVAL', 30)  # 30s aggressive
        
        # State tracking
        self.last_p2p_activity = time.time()  # Track any P2P activity
        self.last_keepalive_sent = 0.0
        self.pending_keepalives: Dict[str, float] = {}  # peer_id -> sent_time
        self.circuit_state = CircuitState.UNKNOWN
        
        # Metrics
        self.metrics = KeepaliveMetrics()
        
        # Control
        self._running = False
        self._keepalive_task: Optional[asyncio.Task] = None
        
        logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Initialized with interval={self.interval}s, "
                   f"suppress_window={self.activity_suppress_window}s, enabled={self.enabled}")
    
    async def start(self):
        """Start the keepalive loop."""
        if not self.enabled:
            logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Disabled by configuration")
            return
        
        if self._running:
            logger.warning(f"P2P_KEEPALIVE ({self.agent_id}): Already running")
            return
        
        self._running = True
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Started keepalive loop")
    
    async def stop(self):
        """Stop the keepalive loop."""
        self._running = False
        
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        
        logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Stopped keepalive loop")
    
    def record_p2p_activity(self):
        """
        Record that P2P activity occurred (workflow message, nudge, broadcast).
        Used for smart suppression of keepalives.
        """
        self.last_p2p_activity = time.time()
    
    def update_circuit_state(self, state: CircuitState):
        """
        Update circuit breaker state for adaptive keepalive behavior.
        
        Args:
            state: Current circuit breaker state
        """
        if state != self.circuit_state:
            logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Circuit state changed: "
                       f"{self.circuit_state.value} -> {state.value}")
            self.circuit_state = state
            self.metrics.circuit_breaker_events += 1
    
    def _should_send_keepalive(self) -> bool:
        """
        Determine if keepalive should be sent based on smart suppression logic.
        
        Returns:
            True if keepalive should be sent, False if suppressed
        """
        current_time = time.time()
        
        # Check if recent P2P activity exists
        time_since_activity = current_time - self.last_p2p_activity
        if time_since_activity < self.activity_suppress_window:
            logger.debug(f"P2P_KEEPALIVE ({self.agent_id}): Suppressed - recent activity "
                        f"{time_since_activity:.1f}s ago")
            self.metrics.suppressed_count += 1
            return False
        
        # Check interval based on circuit state
        interval = self._get_adaptive_interval()
        time_since_last_keepalive = current_time - self.last_keepalive_sent
        
        if time_since_last_keepalive < interval:
            return False
        
        return True
    
    def _get_adaptive_interval(self) -> float:
        """
        Get adaptive keepalive interval based on circuit breaker state.
        
        Returns:
            Keepalive interval in seconds
        """
        if self.circuit_state == CircuitState.HALF_OPEN:
            # Aggressive keepalives to help circuit recovery
            return self.circuit_half_open_interval
        elif self.circuit_state == CircuitState.OPEN:
            # Try to trigger recovery probes
            return self.circuit_half_open_interval
        else:
            # Normal operation
            return self.interval
    
    async def _keepalive_loop(self):
        """Main keepalive loop with adaptive timing."""
        logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Keepalive loop started")
        
        # Initial delay to allow P2P mesh to stabilize
        await asyncio.sleep(30)
        
        while self._running:
            try:
                if self._should_send_keepalive():
                    await self._send_keepalive()
                
                # Check for keepalive timeouts
                await self._check_timeouts()
                
                # Log metrics periodically
                await self._log_metrics()
                
                # Sleep with adaptive interval
                await asyncio.sleep(10)  # Check every 10s, send based on interval
                
            except Exception as e:
                logger.error(f"P2P_KEEPALIVE ({self.agent_id}): Error in keepalive loop: {e}", 
                           exc_info=True)
                await asyncio.sleep(30)  # Back off on error
        
        logger.info(f"P2P_KEEPALIVE ({self.agent_id}): Keepalive loop stopped")
    
    async def _send_keepalive(self):
        """Send keepalive message to all peers."""
        try:
            current_time = time.time()
            
            payload = {
                'agent_id': self.agent_id,
                'timestamp': current_time,
                'circuit_state': self.circuit_state.value,
                'metrics': {
                    'sent': self.metrics.keepalives_sent,
                    'received': self.metrics.keepalives_received,
                    'acks': self.metrics.acks_received
                }
            }
            
            # Broadcast keepalive to all peers
            if self.broadcast_p2p_message:
                success_count = await self.broadcast_p2p_message('P2P_KEEPALIVE', payload)
                
                if success_count > 0:
                    self.last_keepalive_sent = current_time
                    self.metrics.keepalives_sent += 1
                    logger.debug(f"P2P_KEEPALIVE ({self.agent_id}): Sent keepalive to {success_count} peers")
                else:
                    logger.warning(f"P2P_KEEPALIVE ({self.agent_id}): Failed to send keepalive to any peer")
            else:
                logger.warning(f"P2P_KEEPALIVE ({self.agent_id}): No broadcast callback available")
                
        except Exception as e:
            logger.error(f"P2P_KEEPALIVE ({self.agent_id}): Error sending keepalive: {e}")
    
    async def handle_keepalive_received(self, sender_id: str, payload: Dict[str, Any]):
        """
        Handle incoming keepalive message from peer.
        
        Args:
            sender_id: ID of the peer that sent keepalive
            payload: Keepalive message payload
        """
        try:
            self.metrics.keepalives_received += 1
            logger.debug(f"P2P_KEEPALIVE ({self.agent_id}): Received keepalive from {sender_id}")
            
            # Send ACK back to sender
            ack_payload = {
                'agent_id': self.agent_id,
                'timestamp': time.time(),
                'original_timestamp': payload.get('timestamp')
            }
            
            # Send ACK using direct message (not broadcast)
            if self.send_p2p_message:
                success = await self.send_p2p_message(sender_id, 'P2P_KEEPALIVE_ACK', ack_payload)
                if success:
                    logger.debug(f"P2P_KEEPALIVE ({self.agent_id}): Sent ACK to {sender_id}")
                else:
                    logger.warning(f"P2P_KEEPALIVE ({self.agent_id}): Failed to send ACK to {sender_id}")
            
        except Exception as e:
            logger.error(f"P2P_KEEPALIVE ({self.agent_id}): Error handling keepalive: {e}")
    
    async def handle_keepalive_ack(self, sender_id: str, payload: Dict[str, Any]):
        """
        Handle incoming keepalive ACK from peer.
        
        Args:
            sender_id: ID of the peer that sent ACK
            payload: ACK message payload
        """
        try:
            self.metrics.acks_received += 1
            current_time = time.time()
            
            # Calculate latency if original timestamp available
            original_timestamp = payload.get('original_timestamp')
            if original_timestamp:
                latency = current_time - original_timestamp
                self.metrics.last_keepalive_latency = latency
                logger.debug(f"P2P_KEEPALIVE ({self.agent_id}): ACK from {sender_id}, "
                           f"latency={latency*1000:.1f}ms")
            
            self.metrics.last_successful_keepalive = current_time
            
            # Remove from pending if tracked
            if sender_id in self.pending_keepalives:
                del self.pending_keepalives[sender_id]
            
        except Exception as e:
            logger.error(f"P2P_KEEPALIVE ({self.agent_id}): Error handling ACK: {e}")
    
    async def _check_timeouts(self):
        """Check for keepalive timeouts and clean up pending requests."""
        current_time = time.time()
        timed_out = []
        
        for peer_id, sent_time in self.pending_keepalives.items():
            if current_time - sent_time > self.timeout:
                timed_out.append(peer_id)
        
        for peer_id in timed_out:
            del self.pending_keepalives[peer_id]
            self.metrics.timeouts += 1
            logger.warning(f"P2P_KEEPALIVE ({self.agent_id}): Keepalive timeout for peer {peer_id}")
    
    async def _log_metrics(self):
        """Periodically log keepalive metrics."""
        current_time = time.time()
        
        # Log every 5 minutes
        if current_time % 300 < 10:
            logger.info(
                f"P2P_KEEPALIVE_METRICS ({self.agent_id}): "
                f"Sent={self.metrics.keepalives_sent}, "
                f"Received={self.metrics.keepalives_received}, "
                f"ACKs={self.metrics.acks_received}, "
                f"Timeouts={self.metrics.timeouts}, "
                f"Suppressed={self.metrics.suppressed_count}, "
                f"Circuit_Events={self.metrics.circuit_breaker_events}, "
                f"Last_Latency={self.metrics.last_keepalive_latency*1000:.1f}ms"
            )
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get current health status and metrics.
        
        Returns:
            Dictionary with health status and metrics
        """
        current_time = time.time()
        time_since_last_success = current_time - self.metrics.last_successful_keepalive
        
        return {
            'enabled': self.enabled,
            'running': self._running,
            'circuit_state': self.circuit_state.value,
            'last_activity': current_time - self.last_p2p_activity,
            'last_keepalive': current_time - self.last_keepalive_sent,
            'last_success': time_since_last_success,
            'metrics': {
                'sent': self.metrics.keepalives_sent,
                'received': self.metrics.keepalives_received,
                'acks': self.metrics.acks_received,
                'timeouts': self.metrics.timeouts,
                'suppressed': self.metrics.suppressed_count,
                'circuit_events': self.metrics.circuit_breaker_events,
                'latency_ms': self.metrics.last_keepalive_latency * 1000
            }
        }
