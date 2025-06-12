from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import uuid


class SessionStatus(str, Enum):
    """Enum for session statuses."""
    ACTIVE = "active"
    WAITING = "waiting"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
    CLOSED = "closed"


class SessionMetrics(BaseModel):
    """Metrics for a customer session."""
    
    total_messages: int = 0
    user_messages: int = 0
    agent_messages: int = 0
    escalation_count: int = 0
    resolution_time: Optional[float] = None
    wait_time: float = 0.0
    interaction_time: float = 0.0
    satisfaction_score: Optional[float] = None
    agents_involved: List[str] = Field(default_factory=list)
    
    def update_from_context(self, context: "ConversationContext"):
        """Update metrics from conversation context."""
        from models.message import MessageRole
        
        self.total_messages = len(context.messages)
        self.user_messages = sum(
            1 for msg in context.messages if msg.role == MessageRole.USER
        )
        self.agent_messages = sum(
            1 for msg in context.messages if msg.role == MessageRole.ASSISTANT
        )
        
        # Track unique agents
        for msg in context.messages:
            if msg.agent_type and msg.agent_type not in self.agents_involved:
                self.agents_involved.append(msg.agent_type)
        
        # Calculate interaction time
        if context.messages:
            self.interaction_time = context.get_conversation_duration()


class Session(BaseModel):
    """Model for customer service session."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: Optional[str] = None
    status: SessionStatus = SessionStatus.ACTIVE
    current_agent_type: Optional[str] = None
    priority: int = Field(default=0, ge=0, le=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    
    # Session metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    
    # Metrics
    metrics: SessionMetrics = Field(default_factory=SessionMetrics)
    
    # Escalation tracking
    escalation_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    def escalate_to(self, target_agent_type: str, reason: str):
        """Record an escalation event."""
        escalation_event = {
            "from_agent": self.current_agent_type,
            "to_agent": target_agent_type,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        self.escalation_history.append(escalation_event)
        self.current_agent_type = target_agent_type
        self.status = SessionStatus.ESCALATED
        self.metrics.escalation_count += 1
        self.updated_at = datetime.utcnow()
    
    def end_session(self, resolution_status: SessionStatus = SessionStatus.RESOLVED):
        """End the session with specified status."""
        self.status = resolution_status
        self.ended_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        
        if self.created_at and self.ended_at:
            self.metrics.resolution_time = (
                self.ended_at - self.created_at
            ).total_seconds()
    
    def set_satisfaction_score(self, score: float):
        """Set customer satisfaction score (0-10)."""
        if not 0 <= score <= 10:
            raise ValueError("Satisfaction score must be between 0 and 10")
        
        self.metrics.satisfaction_score = score
        self.updated_at = datetime.utcnow()
    
    def add_tag(self, tag: str):
        """Add a tag to the session."""
        if tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.utcnow()
    
    def to_summary(self) -> Dict[str, Any]:
        """Generate session summary."""
        duration = None
        if self.ended_at and self.created_at:
            duration = (self.ended_at - self.created_at).total_seconds()
        
        return {
            "session_id": self.id,
            "customer_id": self.customer_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": duration,
            "total_messages": self.metrics.total_messages,
            "escalation_count": self.metrics.escalation_count,
            "agents_involved": self.metrics.agents_involved,
            "satisfaction_score": self.metrics.satisfaction_score,
            "tags": self.tags,
        }