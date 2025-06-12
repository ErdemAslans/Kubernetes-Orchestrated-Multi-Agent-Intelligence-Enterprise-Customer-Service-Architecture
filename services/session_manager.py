import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import structlog
import redis.asyncio as redis

from models.session import Session, SessionStatus, SessionMetrics
from models.message import Message, MessageRole, ConversationContext
from services.state_manager import StateManager
from agents.base_agent import BaseAgent
from utils.logging_config import get_logger

logger = get_logger(__name__)


class SessionManager:
    """
    Manages individual session lifecycles, analytics, and customer satisfaction tracking.
    """
    
    def __init__(
        self,
        state_manager: StateManager,
        redis_client: Optional[redis.Redis] = None,
        session_timeout_minutes: int = 30,
    ):
        self.state_manager = state_manager
        self.redis_client = redis_client
        self.session_timeout_minutes = session_timeout_minutes
        self.contexts: Dict[str, ConversationContext] = {}
        self._lock = asyncio.Lock()
        
        logger.info(
            "session_manager_initialized",
            timeout_minutes=session_timeout_minutes
        )
    
    async def create_session(
        self,
        customer_id: Optional[str] = None,
        initial_agent_type: str = "customer_service",
        metadata: Optional[Dict] = None,
    ) -> Tuple[Session, BaseAgent]:
        """Create a new session and assign it to an agent."""
        # Create session
        session = Session(
            customer_id=customer_id,
            metadata=metadata or {},
        )
        
        # Create conversation context
        context = ConversationContext(
            session_id=session.id,
            customer_info={"customer_id": customer_id} if customer_id else {},
        )
        
        async with self._lock:
            self.contexts[session.id] = context
        
        # Persist to Redis if available
        await self._persist_session(session)
        await self._persist_context(context)
        
        # Assign to agent
        agent = await self.state_manager.assign_session_to_agent(
            session, initial_agent_type
        )
        
        if not agent:
            session.status = SessionStatus.WAITING
            logger.warning(
                "no_agent_available",
                session_id=session.id,
                requested_type=initial_agent_type
            )
        
        logger.info(
            "session_created",
            session_id=session.id,
            customer_id=customer_id,
            agent_type=agent.agent_type if agent else None,
        )
        
        return session, agent
    
    async def process_message(
        self,
        session_id: str,
        message_content: str,
        customer_metadata: Optional[Dict] = None,
    ) -> Tuple[Message, Session]:
        """Process a customer message in a session."""
        # Get session and context
        session = await self._get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        context = await self._get_context(session_id)
        if not context:
            raise ValueError(f"Context for session {session_id} not found")
        
        # Create user message
        user_message = Message(
            role=MessageRole.USER,
            content=message_content,
            metadata=customer_metadata or {},
        )
        
        # Add to context
        context.add_message(user_message)
        
        # Get current agent
        agent = None
        for ag in self.state_manager.agents.values():
            if ag.agent_type == session.current_agent_type:
                agent = ag
                break
        
        if not agent:
            logger.error(
                "agent_not_found",
                session_id=session_id,
                agent_type=session.current_agent_type
            )
            raise ValueError(f"Agent {session.current_agent_type} not found")
        
        # Process message with agent
        response_message, escalation_target = await agent.process_message(
            user_message, context, session_id
        )
        
        # Add response to context
        context.add_message(response_message)
        
        # Handle escalation if needed
        if escalation_target:
            new_agent = await self.state_manager.escalate_session(
                session_id, escalation_target, "Agent recommended escalation"
            )
            
            if new_agent:
                # Add system message about escalation
                escalation_message = Message(
                    role=MessageRole.SYSTEM,
                    content=f"Transferring you to our {escalation_target} team for better assistance.",
                    metadata={"escalation": True, "target": escalation_target},
                )
                context.add_message(escalation_message)
        
        # Update session
        session.updated_at = datetime.utcnow()
        session.metrics.update_from_context(context)
        
        # Persist updates
        await self._persist_session(session)
        await self._persist_context(context)
        
        logger.info(
            "message_processed",
            session_id=session_id,
            message_count=context.get_message_count(),
            escalated=bool(escalation_target),
        )
        
        return response_message, session
    
    async def end_session(
        self,
        session_id: str,
        satisfaction_score: Optional[float] = None,
        resolution_status: SessionStatus = SessionStatus.RESOLVED,
    ) -> Session:
        """End a session with optional satisfaction score."""
        session = await self._get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # End the session
        session.end_session(resolution_status)
        
        # Set satisfaction score if provided
        if satisfaction_score is not None:
            session.set_satisfaction_score(satisfaction_score)
        
        # Get final context for analytics
        context = await self._get_context(session_id)
        if context:
            session.metrics.update_from_context(context)
            
            # Analyze conversation for tags
            tags = await self._analyze_conversation(context)
            for tag in tags:
                session.add_tag(tag)
        
        # Release from state manager
        await self.state_manager.release_session(session_id)
        
        # Persist final state
        await self._persist_session(session)
        
        # Schedule cleanup
        asyncio.create_task(self._schedule_cleanup(session_id))
        
        logger.info(
            "session_ended",
            session_id=session_id,
            status=resolution_status,
            satisfaction_score=satisfaction_score,
            duration=session.metrics.resolution_time,
        )
        
        return session
    
    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return await self._get_session(session_id)
    
    async def get_session_transcript(self, session_id: str) -> Optional[str]:
        """Get the full transcript of a session."""
        context = await self._get_context(session_id)
        if not context:
            return None
        
        return context.to_transcript()
    
    async def get_active_sessions(self) -> List[Session]:
        """Get all active sessions."""
        sessions = []
        
        for session_id in self.state_manager.active_sessions:
            session = await self._get_session(session_id)
            if session:
                sessions.append(session)
        
        return sessions
    
    async def get_session_analytics(
        self, start_date: datetime, end_date: datetime
    ) -> Dict:
        """Get analytics for sessions in a date range."""
        # This would query from database in production
        analytics = {
            "total_sessions": 0,
            "average_duration": 0.0,
            "average_messages": 0.0,
            "average_satisfaction": 0.0,
            "resolution_rate": 0.0,
            "escalation_rate": 0.0,
            "top_tags": [],
            "agent_performance": {},
        }
        
        # Implementation would aggregate from persistent storage
        return analytics
    
    async def _get_session(self, session_id: str) -> Optional[Session]:
        """Get session from cache or Redis."""
        # Check active sessions first
        if session_id in self.state_manager.active_sessions:
            return self.state_manager.active_sessions[session_id]
        
        # Try Redis if available
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"session:{session_id}")
                if data:
                    return Session.model_validate_json(data)
            except Exception as e:
                logger.error(
                    "redis_get_session_error",
                    session_id=session_id,
                    error=str(e)
                )
        
        return None
    
    async def _get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Get context from cache or Redis."""
        # Check memory cache first
        async with self._lock:
            if session_id in self.contexts:
                return self.contexts[session_id]
        
        # Try Redis if available
        if self.redis_client:
            try:
                data = await self.redis_client.get(f"context:{session_id}")
                if data:
                    context = ConversationContext.model_validate_json(data)
                    # Cache it
                    async with self._lock:
                        self.contexts[session_id] = context
                    return context
            except Exception as e:
                logger.error(
                    "redis_get_context_error",
                    session_id=session_id,
                    error=str(e)
                )
        
        return None
    
    async def _persist_session(self, session: Session):
        """Persist session to Redis."""
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"session:{session.id}",
                    timedelta(hours=24),
                    session.model_dump_json(),
                )
            except Exception as e:
                logger.error(
                    "redis_persist_session_error",
                    session_id=session.id,
                    error=str(e)
                )
    
    async def _persist_context(self, context: ConversationContext):
        """Persist context to Redis."""
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"context:{context.session_id}",
                    timedelta(hours=24),
                    context.model_dump_json(),
                )
            except Exception as e:
                logger.error(
                    "redis_persist_context_error",
                    session_id=context.session_id,
                    error=str(e)
                )
    
    async def _analyze_conversation(self, context: ConversationContext) -> List[str]:
        """Analyze conversation and generate tags."""
        tags = []
        
        # Analyze message content for common themes
        all_content = " ".join([msg.content.lower() for msg in context.messages])
        
        # Product-related tags
        if any(word in all_content for word in ["product", "feature", "functionality"]):
            tags.append("product-inquiry")
        
        # Support-related tags
        if any(word in all_content for word in ["error", "bug", "issue", "problem"]):
            tags.append("technical-support")
        
        # Sales-related tags
        if any(word in all_content for word in ["price", "cost", "buy", "purchase"]):
            tags.append("sales-inquiry")
        
        # Satisfaction indicators
        if any(word in all_content for word in ["thank", "great", "excellent", "helpful"]):
            tags.append("positive-experience")
        elif any(word in all_content for word in ["frustrated", "angry", "terrible", "worst"]):
            tags.append("negative-experience")
        
        # Escalation
        if len(context.metadata.get("escalations", [])) > 0:
            tags.append("escalated")
        
        return tags
    
    async def _schedule_cleanup(self, session_id: str):
        """Schedule cleanup of session data after delay."""
        # Wait before cleanup
        await asyncio.sleep(3600)  # 1 hour
        
        # Remove from memory cache
        async with self._lock:
            if session_id in self.contexts:
                del self.contexts[session_id]
        
        logger.info("session_cleaned_up", session_id=session_id)