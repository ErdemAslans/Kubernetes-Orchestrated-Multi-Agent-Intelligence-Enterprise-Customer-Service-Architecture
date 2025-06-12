import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
import uuid

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import redis.asyncio as redis
import structlog

from agents import CustomerServiceAgent, TechnicalSupportAgent, SalesSpecialistAgent
from services import StateManager, SessionManager
from models import Session, SessionStatus
from utils import setup_logging, get_logger, add_correlation_id

# Setup logging
setup_logging(
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    json_logs=os.getenv("DEBUG", "false").lower() != "true"
)

logger = get_logger(__name__)


# Request/Response models
class CreateSessionRequest(BaseModel):
    customer_id: Optional[str] = None
    initial_agent_type: str = Field(default="customer_service")
    metadata: Optional[Dict[str, Any]] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str
    agent_type: Optional[str]
    message: str


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    metadata: Optional[Dict[str, Any]] = None


class SendMessageResponse(BaseModel):
    message_id: str
    content: str
    agent_type: str
    timestamp: str
    escalated: bool = False


class EndSessionRequest(BaseModel):
    satisfaction_score: Optional[float] = Field(None, ge=0, le=10)
    resolution_status: SessionStatus = SessionStatus.RESOLVED


class SessionDetailsResponse(BaseModel):
    session_id: str
    status: str
    created_at: str
    ended_at: Optional[str]
    current_agent_type: Optional[str]
    total_messages: int
    escalation_count: int
    satisfaction_score: Optional[float]
    tags: list[str]


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, Any]


class SystemMetricsResponse(BaseModel):
    total_sessions: int
    active_sessions: int
    completed_sessions: int
    average_wait_time: float
    average_resolution_time: float
    total_escalations: int
    agent_workload: Dict[str, Any]
    timestamp: str


# Global instances
state_manager: Optional[StateManager] = None
session_manager: Optional[SessionManager] = None
redis_client: Optional[redis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global state_manager, session_manager, redis_client
    
    logger.info("application_starting")
    
    # Initialize Redis
    if os.getenv("REDIS_HOST"):
        try:
            redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                db=int(os.getenv("REDIS_DB", 0)),
                password=os.getenv("REDIS_PASSWORD"),
                decode_responses=True,
            )
            await redis_client.ping()
            logger.info("redis_connected")
        except Exception as e:
            logger.error("redis_connection_failed", error=str(e))
            redis_client = None
    
    # Initialize state manager
    state_manager = StateManager(redis_client=redis_client)
    await state_manager.start()
    
    # Initialize session manager
    session_manager = SessionManager(
        state_manager=state_manager,
        redis_client=redis_client,
        session_timeout_minutes=int(os.getenv("SESSION_TIMEOUT_MINUTES", 30))
    )
    
    # Initialize and register agents
    agents = [
        CustomerServiceAgent(
            agent_id="cs-agent-1",
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        ),
        TechnicalSupportAgent(
            agent_id="tech-agent-1",
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        ),
        SalesSpecialistAgent(
            agent_id="sales-agent-1",
            project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        ),
    ]
    
    for agent in agents:
        state_manager.register_agent(agent)
    
    logger.info("agents_initialized", agent_count=len(agents))
    
    yield
    
    # Shutdown
    logger.info("application_stopping")
    
    # Stop state manager
    if state_manager:
        await state_manager.stop()
    
    # Close Redis
    if redis_client:
        await redis_client.close()


# Create FastAPI app
app = FastAPI(
    title="Multi-Agent Customer Service System",
    description="Production-ready multi-agent customer service system with Vertex AI",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware for correlation IDs
@app.middleware("http")
async def correlation_id_middleware(request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    add_correlation_id(correlation_id)
    
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    
    return response


# API Endpoints
@app.post(
    "/api/v1/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sessions"]
)
async def create_session(request: CreateSessionRequest):
    """Create a new customer service session."""
    try:
        session, agent = await session_manager.create_session(
            customer_id=request.customer_id,
            initial_agent_type=request.initial_agent_type,
            metadata=request.metadata,
        )
        
        return CreateSessionResponse(
            session_id=session.id,
            status=session.status,
            agent_type=agent.agent_type if agent else None,
            message="Session created successfully" if agent else "Session created, waiting for available agent"
        )
    
    except Exception as e:
        logger.error("create_session_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session"
        )


@app.post(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
    tags=["sessions"]
)
async def send_message(session_id: str, request: SendMessageRequest):
    """Send a message to an agent in a session."""
    try:
        response_message, session = await session_manager.process_message(
            session_id=session_id,
            message_content=request.content,
            customer_metadata=request.metadata,
        )
        
        escalated = len(session.escalation_history) > 0
        
        return SendMessageResponse(
            message_id=response_message.id,
            content=response_message.content,
            agent_type=response_message.agent_type or "unknown",
            timestamp=response_message.timestamp.isoformat(),
            escalated=escalated,
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("send_message_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message"
        )


@app.get(
    "/api/v1/sessions/{session_id}",
    response_model=SessionDetailsResponse,
    tags=["sessions"]
)
async def get_session_details(session_id: str):
    """Get details and analytics for a session."""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found"
            )
        
        return SessionDetailsResponse(
            session_id=session.id,
            status=session.status,
            created_at=session.created_at.isoformat(),
            ended_at=session.ended_at.isoformat() if session.ended_at else None,
            current_agent_type=session.current_agent_type,
            total_messages=session.metrics.total_messages,
            escalation_count=session.metrics.escalation_count,
            satisfaction_score=session.metrics.satisfaction_score,
            tags=session.tags,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_session_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session"
        )


@app.post(
    "/api/v1/sessions/{session_id}/end",
    response_model=SessionDetailsResponse,
    tags=["sessions"]
)
async def end_session(session_id: str, request: EndSessionRequest):
    """End a session with optional satisfaction score."""
    try:
        session = await session_manager.end_session(
            session_id=session_id,
            satisfaction_score=request.satisfaction_score,
            resolution_status=request.resolution_status,
        )
        
        return SessionDetailsResponse(
            session_id=session.id,
            status=session.status,
            created_at=session.created_at.isoformat(),
            ended_at=session.ended_at.isoformat() if session.ended_at else None,
            current_agent_type=session.current_agent_type,
            total_messages=session.metrics.total_messages,
            escalation_count=session.metrics.escalation_count,
            satisfaction_score=session.metrics.satisfaction_score,
            tags=session.tags,
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error("end_session_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to end session"
        )


@app.get(
    "/api/v1/sessions/{session_id}/transcript",
    tags=["sessions"]
)
async def get_session_transcript(session_id: str):
    """Get the full transcript of a session."""
    try:
        transcript = await session_manager.get_session_transcript(session_id)
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session transcript not found"
            )
        
        return {"session_id": session_id, "transcript": transcript}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_transcript_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transcript"
        )


@app.get(
    "/api/v1/system/metrics",
    response_model=SystemMetricsResponse,
    tags=["system"]
)
async def get_system_metrics():
    """Get system performance metrics."""
    try:
        metrics = state_manager.get_system_metrics()
        workload = state_manager.get_agent_workload()
        
        return SystemMetricsResponse(
            total_sessions=metrics["total_sessions"],
            active_sessions=metrics["active_sessions"],
            completed_sessions=metrics["completed_sessions"],
            average_wait_time=metrics["average_wait_time"],
            average_resolution_time=metrics["average_resolution_time"],
            total_escalations=metrics["total_escalations"],
            agent_workload=workload,
            timestamp=metrics["timestamp"],
        )
    
    except Exception as e:
        logger.error("get_metrics_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve metrics"
        )


@app.get(
    "/api/v1/system/health",
    response_model=HealthCheckResponse,
    tags=["system"]
)
async def health_check():
    """Health check endpoint for Kubernetes."""
    try:
        health = await state_manager.health_check()
        
        return HealthCheckResponse(
            status=health["status"],
            timestamp=health["timestamp"],
            services={
                "state_manager": health["status"],
                "redis": "healthy" if redis_client else "unavailable",
                "agents": health["agent_health"],
            }
        )
    
    except Exception as e:
        logger.error("health_check_error", error=str(e))
        return HealthCheckResponse(
            status="unhealthy",
            timestamp=datetime.utcnow().isoformat(),
            services={"error": str(e)}
        )


# Demo endpoints (only if enabled)
if os.getenv("ENABLE_DEMO_MODE", "false").lower() == "true":
    from fastapi import BackgroundTasks
    
    class DemoScenarioRequest(BaseModel):
        scenario: str = Field(description="Demo scenario to run")
        customer_id: Optional[str] = None
    
    @app.post("/api/v1/demo/scenario", tags=["demo"])
    async def run_demo_scenario(
        request: DemoScenarioRequest,
        background_tasks: BackgroundTasks
    ):
        """Run a predefined demo scenario."""
        # Implementation would include predefined conversation flows
        return {
            "message": "Demo scenario started",
            "scenario": request.scenario,
            "session_id": str(uuid.uuid4())
        }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_config=None,  # Use our custom logging
    )