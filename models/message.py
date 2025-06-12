from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
import uuid


class MessageRole(str, Enum):
    """Enum for message roles in conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """Model for individual messages in a conversation."""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('content')
    def content_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Message content cannot be empty')
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConversationContext(BaseModel):
    """Model for maintaining conversation context."""
    
    session_id: str
    messages: List[Message] = Field(default_factory=list)
    customer_info: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    def add_message(self, message: Message):
        """Add a message to the conversation."""
        self.messages.append(message)
        self.updated_at = datetime.utcnow()
    
    def get_message_count(self) -> int:
        """Get total number of messages."""
        return len(self.messages)
    
    def get_last_user_message(self) -> Optional[Message]:
        """Get the last message from the user."""
        for message in reversed(self.messages):
            if message.role == MessageRole.USER:
                return message
        return None
    
    def get_conversation_duration(self) -> float:
        """Get conversation duration in seconds."""
        if not self.messages:
            return 0.0
        
        first_message = self.messages[0]
        last_message = self.messages[-1]
        return (last_message.timestamp - first_message.timestamp).total_seconds()
    
    def to_transcript(self) -> str:
        """Convert conversation to readable transcript."""
        transcript_lines = []
        
        for msg in self.messages:
            role = msg.role.value.capitalize()
            if msg.agent_type:
                role = f"{role} ({msg.agent_type})"
            
            transcript_lines.append(
                f"[{msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {role}: {msg.content}"
            )
        
        return "\n".join(transcript_lines)