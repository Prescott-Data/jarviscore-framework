"""
Step Output Broadcaster for P2P Step Output Sharing
Handles broadcasting and caching step outputs between agents in the P2P network
"""
import asyncio
import json
import logging
import time
import os
import uuid
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class StepExecutionResult:
    """Data class for step execution results"""
    step_id: str
    workflow_id: str
    status: str  # "success", "failed", "in_progress"
    output_data: Dict[str, Any]
    agent_id: str
    timestamp: float
    execution_time: Optional[float] = None
    retry_count: Optional[int] = None
    result_status: Optional[str] = None
    error_message: Optional[str] = None

class StepOutputBroadcaster:
    """
    Service class for managing step output broadcasting and caching in P2P network
    
    This class manages:
    - Broadcasting step execution results to peers
    - Caching step outputs from all agents
    - Processing step output broadcasts
    - Persistent storage of step results
    
    Note: Request/response functionality has been replaced by the nudging system
    """
    
    def __init__(self, agent_id: str, zmq_agent=None, swim_node=None):
        self.agent_id = agent_id
        self.zmq_agent = zmq_agent
        self.swim_node = swim_node
        
        # Cache for step outputs from all agents (including self)
        self.step_outputs: Dict[str, StepExecutionResult] = {}
        
        # Track message acknowledgments for broadcasts
        self.pending_acks: Dict[str, Dict[str, Any]] = {}
        
        # Create directories for persistence
        os.makedirs("StepOutputs", exist_ok=True)
        
        logger.info(f"Step Output Broadcaster service initialized for agent {agent_id}")
    
    async def broadcast_step_result(
        self, 
        step_id: str, 
        workflow_id: str, 
        output_data: Dict[str, Any], 
        status: str,
        execution_metadata: Dict[str, Any] = None
    ) -> bool:
        """
        Broadcast step execution result to all peers
        
        Args:
            step_id: The step ID
            workflow_id: The workflow ID
            output_data: The step output data
            status: The step status ("success", "failed", "in_progress")
            execution_metadata: Optional execution metadata
            
        Returns:
            bool: True if broadcast was successful
        """
        try:
            # Extract execution details from metadata
            execution_time = execution_metadata.get('execution_time') if execution_metadata else None
            retry_count = execution_metadata.get('retry_count') if execution_metadata else None
            result_status = execution_metadata.get('result_status') if execution_metadata else None
            error_message = execution_metadata.get('error') if execution_metadata else None
            
            # Create step execution result
            result = StepExecutionResult(
                step_id=step_id,
                workflow_id=workflow_id,
                status=status,
                output_data=output_data,
                agent_id=self.agent_id,
                timestamp=time.time(),
                execution_time=execution_time,
                retry_count=retry_count,
                result_status=result_status,
                error_message=error_message
            )
            
            # Store in local cache
            cache_key = f"{workflow_id}:{step_id}"
            self.step_outputs[cache_key] = result
            
            # Persist to file
            await self._persist_step_result(result)
            
            # Broadcast to peers
            if self.zmq_agent:
                success = await self._broadcast_to_peers(result)
                if success:
                    logger.info(f"Successfully broadcasted step result for {step_id}")
                    return True
                else:
                    logger.warning(f"Failed to broadcast step result for {step_id}")
                    return False
            else:
                logger.debug("No ZMQ agent available for broadcasting")
                return True  # Still successful locally
                
        except Exception as e:
            logger.error(f"Error broadcasting step result for {step_id}: {e}")
            return False
    
    # Public methods for IntegrationAgent to call for message processing
    
    async def handle_step_output_broadcast(
        self, 
        sender_swim_id: str, 
        message_data: Dict[str, Any],
        send_ack_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Handle incoming step output broadcast from peer (called by IntegrationAgent)
        
        Args:
            sender_swim_id: The SWIM ID of the sender
            message_data: The message data containing step result
            send_ack_callback: Optional callback to send acknowledgment
            
        Returns:
            Dict with processing result
        """
        try:
            message_id = message_data.get('id', str(uuid.uuid4()))
            step_result_data = message_data.get('step_result', {})
            
            # Send acknowledgment if callback provided
            if send_ack_callback:
                await send_ack_callback(sender_swim_id, message_id, "STEP_OUTPUT_BROADCAST")
            
            # Create StepExecutionResult from received data
            result = StepExecutionResult(**step_result_data)
            
            logger.info(f"Processing step output broadcast for {result.step_id} from {result.agent_id}")
            
            # Store in local cache
            cache_key = f"{result.workflow_id}:{result.step_id}"
            self.step_outputs[cache_key] = result
            
            # Persist to file
            await self._persist_step_result(result)
            
            logger.debug(f"Stored broadcasted step output for {result.step_id}")
            
            return {"status": "success", "message": "Broadcast processed successfully"}
            
        except Exception as e:
            logger.error(f"Error handling step output broadcast: {e}")
            return {"status": "error", "message": str(e)}
    
    async def handle_step_output_ack(
        self, 
        sender_swim_id: str, 
        message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle acknowledgment for step output messages (called by IntegrationAgent)
        
        Args:
            sender_swim_id: The SWIM ID of the sender
            message_data: The message data containing ACK details
            
        Returns:
            Dict with processing result
        """
        try:
            # Extract ACK details
            ack_for_message_id = message_data.get('ack_for')
            ack_type = message_data.get('ack_type', 'delivery')
            success = message_data.get('success', True)
            
            if ack_for_message_id in self.pending_acks:
                ack_data = self.pending_acks[ack_for_message_id]
                step_id = ack_data.get('step_id')
                
                logger.debug(f"Processing {ack_type} ACK from {sender_swim_id} for step {step_id} (message {ack_for_message_id})")
                
                # Remove from pending ACKs if it's a processing ACK or if delivery failed
                if ack_type == 'processing' or (ack_type == 'delivery' and not success):
                    del self.pending_acks[ack_for_message_id]
                
                return {"status": "success", "message": "ACK processed"}
            else:
                logger.debug(f"Received ACK for unknown message {ack_for_message_id} from {sender_swim_id}")
                return {"status": "unknown", "message": "ACK for unknown message"}
                
        except Exception as e:
            logger.error(f"Error handling step output ACK: {e}")
            return {"status": "error", "message": str(e)}
    
    # Private helper methods
    
    async def _broadcast_to_peers(self, result: StepExecutionResult) -> bool:
        """Broadcast step result to all peers using reliable messaging"""
        try:
            # Get all alive peers
            peers = self._get_alive_peers()
            
            if not peers:
                logger.debug("No peers available for broadcasting")
                return True  # Not an error if no peers
            
            # Generate a unique message ID for tracking
            message_id = str(uuid.uuid4())
            
            # Send to each peer using reliability manager
            success_count = 0
            for peer_id in peers:
                try:
                    # Use the send_message_base method which leverages the reliability manager
                    success = await self.zmq_agent.send_message_base(
                        peer_id,
                        "STEP_OUTPUT_BROADCAST",
                        "step_output_data",
                        json.dumps(asdict(result)),
                        f"StepBroadcast_{result.step_id}"
                    )
                    
                    if success:
                        success_count += 1
                        logger.debug(f"Broadcasted step result to peer {peer_id}")
                        
                        # Track for acknowledgment
                        self.pending_acks[message_id] = {
                            "peer_id": peer_id,
                            "step_id": result.step_id,
                            "workflow_id": result.workflow_id,
                            "timestamp": time.time()
                        }
                    else:
                        logger.warning(f"Failed to broadcast to peer {peer_id}")
                        
                except Exception as e:
                    logger.error(f"Error broadcasting to peer {peer_id}: {e}")
            
            logger.info(f"Broadcasted step result to {success_count}/{len(peers)} peers")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Error broadcasting to peers: {e}")
            return False
    
    def _get_alive_peers(self) -> List[str]:
        """Get list of alive peers from SWIM node"""
        peers = []
        
        if self.swim_node and hasattr(self.swim_node, 'members'):
            try:
                alive_members = self.swim_node.members.get_alive_members(exclude_self=True)
                peers = [f"{member.addr[0]}:{member.addr[1]}" for member in alive_members]
            except Exception as e:
                logger.debug(f"Error getting alive peers: {e}")
        
        return peers
    
    async def _persist_step_result(self, result: StepExecutionResult):
        """Persist step result to file"""
        try:
            filename = f"step_{result.step_id}_{result.workflow_id}_result.json"
            filepath = os.path.join("StepOutputs", filename)
            
            with open(filepath, 'w') as f:
                json.dump(asdict(result), f, indent=2)
                
            logger.debug(f"Persisted step result for {result.step_id}")
            
        except Exception as e:
            logger.error(f"Error persisting step result: {e}")
    
    def get_cached_output(self, step_id: str, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get cached step output"""
        cache_key = f"{workflow_id}:{step_id}"
        if cache_key in self.step_outputs:
            result = self.step_outputs[cache_key]
            if result.status == "success":
                return {
                    "status": "success",
                    "data": result.output_data,
                    "agent_id": result.agent_id,
                    "timestamp": result.timestamp,
                    "execution_time": result.execution_time,
                    "retry_count": result.retry_count
                }
        return None
    
    def cleanup_old_outputs(self, max_age_hours: int = 24):
        """Clean up old cached outputs"""
        try:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            
            # Clean up memory cache
            keys_to_remove = []
            for key, result in self.step_outputs.items():
                if current_time - result.timestamp > max_age_seconds:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.step_outputs[key]
            
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} old step outputs from cache")
            
            # Clean up files
            output_dir = "StepOutputs"
            if os.path.exists(output_dir):
                files_removed = 0
                for filename in os.listdir(output_dir):
                    filepath = os.path.join(output_dir, filename)
                    if os.path.isfile(filepath):
                        file_age = current_time - os.path.getmtime(filepath)
                        if file_age > max_age_seconds:
                            os.remove(filepath)
                            files_removed += 1
                
                if files_removed > 0:
                    logger.info(f"Cleaned up {files_removed} old step output files")
            
            # Clean up pending ACKs
            ack_ids_to_remove = []
            for ack_id, ack_data in self.pending_acks.items():
                if current_time - ack_data.get('timestamp', 0) > max_age_seconds:
                    ack_ids_to_remove.append(ack_id)
            
            for ack_id in ack_ids_to_remove:
                del self.pending_acks[ack_id]
            
            if ack_ids_to_remove:
                logger.info(f"Cleaned up {len(ack_ids_to_remove)} old pending ACKs")
                    
        except Exception as e:
            logger.error(f"Error cleaning up old outputs: {e}")
