import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import structlog
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel, Content, Part
from tenacity import retry, stop_after_attempt, wait_exponential

from models.message import Message, MessageRole, ConversationContext
from utils.logging_config import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all AI agents in the system."""
    
    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        model_name: str = "gemini-1.5-pro",
        temperature: float = 0.5,
        max_output_tokens: int = 2048,
        top_p: float = 0.95,
        project_id: Optional[str] = None,
        location: str = "us-central1",
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.top_p = top_p
        self.project_id = project_id
        self.location = location
        
        # Performance metrics
        self.metrics = {
            "total_requests": 0,
            "successful_responses": 0,
            "failed_responses": 0,
            "total_response_time": 0.0,
            "escalations": 0,
        }
        
        # Initialize Vertex AI
        self._initialize_vertex_ai()
        
        # Agent-specific configuration
        self.system_prompt = self._get_system_prompt()
        self.escalation_keywords = self._get_escalation_keywords()
        
        logger.info(
            "agent_initialized",
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            model=self.model_name,
            temperature=self.temperature,
        )
    
    def _initialize_vertex_ai(self):
        """Initialize Vertex AI with proper configuration."""
        try:
            if self.project_id:
                aiplatform.init(project=self.project_id, location=self.location)
            
            self.model = GenerativeModel(
                self.model_name,
                generation_config={
                    "temperature": self.temperature,
                    "max_output_tokens": self.max_output_tokens,
                    "top_p": self.top_p,
                }
            )
            logger.info("vertex_ai_initialized", model=self.model_name)
        except Exception as e:
            logger.error("vertex_ai_initialization_failed", error=str(e))
            raise
    
    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Get the system prompt for this agent type."""
        pass
    
    @abstractmethod
    def _get_escalation_keywords(self) -> List[str]:
        """Get keywords that trigger escalation for this agent."""
        pass
    
    @abstractmethod
    def _get_routing_rules(self) -> Dict[str, str]:
        """Get routing rules for this agent."""
        pass
    
    async def process_message(
        self,
        message: Message,
        context: ConversationContext,
        session_id: str,
    ) -> Tuple[Message, Optional[str]]:
        """
        Process an incoming message and generate a response.
        
        Returns:
            Tuple of (response_message, escalation_target_agent_type)
        """
        start_time = time.time()
        self.metrics["total_requests"] += 1
        
        try:
            # Check for escalation triggers
            escalation_target = await self._check_escalation(message, context)
            
            # Generate response using Vertex AI
            response_content = await self._generate_response(message, context)
            
            # Create response message
            response_message = Message(
                role=MessageRole.ASSISTANT,
                content=response_content,
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                metadata={
                    "session_id": session_id,
                    "processing_time": time.time() - start_time,
                    "model": self.model_name,
                }
            )
            
            # Update metrics
            self.metrics["successful_responses"] += 1
            self.metrics["total_response_time"] += time.time() - start_time
            
            if escalation_target:
                self.metrics["escalations"] += 1
                logger.info(
                    "escalation_triggered",
                    session_id=session_id,
                    from_agent=self.agent_type,
                    to_agent=escalation_target,
                )
            
            return response_message, escalation_target
            
        except Exception as e:
            self.metrics["failed_responses"] += 1
            logger.error(
                "message_processing_failed",
                session_id=session_id,
                error=str(e),
                agent_id=self.agent_id,
            )
            
            # Return fallback response
            fallback_message = Message(
                role=MessageRole.ASSISTANT,
                content=self._get_fallback_response(),
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                metadata={"error": str(e), "session_id": session_id},
            )
            return fallback_message, None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def _generate_response(
        self, message: Message, context: ConversationContext
    ) -> str:
        """Generate response using Vertex AI with retry logic."""
        try:
            # Prepare conversation history
            history = self._prepare_conversation_history(context)
            
            # Add system prompt
            full_prompt = f"{self.system_prompt}\n\n{history}\n\nUser: {message.content}\nAssistant:"
            
            # Generate response
            response = await asyncio.to_thread(
                self.model.generate_content, full_prompt
            )
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(
                "vertex_ai_generation_failed",
                error=str(e),
                agent_id=self.agent_id,
            )
            raise
    
    def _prepare_conversation_history(self, context: ConversationContext) -> str:
        """Prepare conversation history for the model."""
        history_parts = []
        
        # Include recent messages (last 10)
        recent_messages = context.messages[-10:]
        
        for msg in recent_messages:
            role = "User" if msg.role == MessageRole.USER else "Assistant"
            history_parts.append(f"{role}: {msg.content}")
        
        return "\n".join(history_parts)
    
    async def _check_escalation(
        self, message: Message, context: ConversationContext
    ) -> Optional[str]:
        """Check if the message requires escalation to another agent."""
        message_lower = message.content.lower()
        
        # Check escalation keywords
        for keyword in self.escalation_keywords:
            if keyword in message_lower:
                # Determine target agent based on routing rules
                routing_rules = self._get_routing_rules()
                
                for pattern, target_agent in routing_rules.items():
                    if pattern in message_lower:
                        return target_agent
        
        # Check sentiment for frustration (simplified)
        frustration_indicators = [
            "frustrated", "angry", "upset", "terrible",
            "worst", "horrible", "unacceptable", "speak to manager"
        ]
        
        if any(indicator in message_lower for indicator in frustration_indicators):
            return "supervisor"
        
        return None
    
    def _get_fallback_response(self) -> str:
        """Get a fallback response when generation fails."""
        return (
            "I apologize for the inconvenience. I'm experiencing technical difficulties "
            "at the moment. Please try again in a few moments, or I can transfer you "
            "to another representative if you prefer."
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current agent metrics."""
        avg_response_time = (
            self.metrics["total_response_time"] / self.metrics["successful_responses"]
            if self.metrics["successful_responses"] > 0
            else 0
        )
        
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "total_requests": self.metrics["total_requests"],
            "successful_responses": self.metrics["successful_responses"],
            "failed_responses": self.metrics["failed_responses"],
            "average_response_time": avg_response_time,
            "escalations": self.metrics["escalations"],
            "success_rate": (
                self.metrics["successful_responses"] / self.metrics["total_requests"]
                if self.metrics["total_requests"] > 0
                else 0
            ),
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the agent."""
        try:
            # Test model connectivity
            test_response = await asyncio.to_thread(
                self.model.generate_content,
                "Respond with 'OK' if you're operational."
            )
            
            return {
                "status": "healthy",
                "agent_id": self.agent_id,
                "agent_type": self.agent_type,
                "model": self.model_name,
                "metrics": self.get_metrics(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "agent_id": self.agent_id,
                "agent_type": self.agent_type,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }