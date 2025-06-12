import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import structlog
from collections import defaultdict

from agents.base_agent import BaseAgent
from models.session import Session, SessionStatus
from utils.logging_config import get_logger

logger = get_logger(__name__)


class StateManager:
    """
    Global system state manager that handles agent workload balancing,
    metrics tracking, and system-wide coordination.
    """
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.agents: Dict[str, BaseAgent] = {}
        self.active_sessions: Dict[str, Session] = {}
        self.agent_load: Dict[str, int] = defaultdict(int)
        self.system_metrics = {
            "total_sessions": 0,
            "active_sessions": 0,
            "completed_sessions": 0,
            "average_wait_time": 0.0,
            "average_resolution_time": 0.0,
            "total_escalations": 0,
        }
        self._lock = asyncio.Lock()
        
        # Start background tasks
        self._cleanup_task = None
        self._metrics_task = None
        
        logger.info("state_manager_initialized")
    
    async def start(self):
        """Start background tasks."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._metrics_task = asyncio.create_task(self._metrics_aggregation_loop())
        logger.info("state_manager_started")
    
    async def stop(self):
        """Stop background tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._metrics_task:
            self._metrics_task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(
            self._cleanup_task,
            self._metrics_task,
            return_exceptions=True
        )
        logger.info("state_manager_stopped")
    
    def register_agent(self, agent: BaseAgent):
        """Register an agent with the state manager."""
        self.agents[agent.agent_id] = agent
        self.agent_load[agent.agent_id] = 0
        logger.info(
            "agent_registered",
            agent_id=agent.agent_id,
            agent_type=agent.agent_type
        )
    
    def unregister_agent(self, agent_id: str):
        """Unregister an agent."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            del self.agent_load[agent_id]
            logger.info("agent_unregistered", agent_id=agent_id)
    
    async def assign_session_to_agent(
        self, session: Session, preferred_agent_type: Optional[str] = None
    ) -> Optional[BaseAgent]:
        """
        Assign a session to an available agent based on load balancing.
        """
        async with self._lock:
            # Filter agents by type if specified
            available_agents = [
                agent for agent in self.agents.values()
                if not preferred_agent_type or agent.agent_type == preferred_agent_type
            ]
            
            if not available_agents:
                logger.warning(
                    "no_agents_available",
                    preferred_type=preferred_agent_type
                )
                return None
            
            # Find agent with lowest load
            best_agent = min(
                available_agents,
                key=lambda a: self.agent_load[a.agent_id]
            )
            
            # Assign session
            self.active_sessions[session.id] = session
            self.agent_load[best_agent.agent_id] += 1
            session.current_agent_type = best_agent.agent_type
            
            # Update metrics
            self.system_metrics["total_sessions"] += 1
            self.system_metrics["active_sessions"] = len(self.active_sessions)
            
            logger.info(
                "session_assigned",
                session_id=session.id,
                agent_id=best_agent.agent_id,
                agent_type=best_agent.agent_type,
                current_load=self.agent_load[best_agent.agent_id]
            )
            
            return best_agent
    
    async def release_session(self, session_id: str):
        """Release a session from an agent."""
        async with self._lock:
            if session_id not in self.active_sessions:
                return
            
            session = self.active_sessions[session_id]
            
            # Find the agent handling this session
            for agent in self.agents.values():
                if agent.agent_type == session.current_agent_type:
                    self.agent_load[agent.agent_id] = max(
                        0, self.agent_load[agent.agent_id] - 1
                    )
                    break
            
            # Remove from active sessions
            del self.active_sessions[session_id]
            
            # Update metrics
            self.system_metrics["active_sessions"] = len(self.active_sessions)
            self.system_metrics["completed_sessions"] += 1
            
            logger.info(
                "session_released",
                session_id=session_id,
                final_status=session.status
            )
    
    async def escalate_session(
        self, session_id: str, target_agent_type: str, reason: str
    ) -> Optional[BaseAgent]:
        """Escalate a session to a different agent type."""
        async with self._lock:
            if session_id not in self.active_sessions:
                logger.warning("session_not_found", session_id=session_id)
                return None
            
            session = self.active_sessions[session_id]
            current_agent_type = session.current_agent_type
            
            # Release from current agent
            for agent in self.agents.values():
                if agent.agent_type == current_agent_type:
                    self.agent_load[agent.agent_id] = max(
                        0, self.agent_load[agent.agent_id] - 1
                    )
                    break
            
            # Record escalation
            session.escalate_to(target_agent_type, reason)
            
            # Assign to new agent
            new_agent = await self.assign_session_to_agent(
                session, target_agent_type
            )
            
            # Update metrics
            self.system_metrics["total_escalations"] += 1
            
            logger.info(
                "session_escalated",
                session_id=session_id,
                from_agent=current_agent_type,
                to_agent=target_agent_type,
                reason=reason
            )
            
            return new_agent
    
    def get_agent_workload(self) -> Dict[str, Dict[str, Any]]:
        """Get current workload for all agents."""
        workload = {}
        
        for agent_id, agent in self.agents.items():
            workload[agent_id] = {
                "agent_type": agent.agent_type,
                "current_load": self.agent_load[agent_id],
                "metrics": agent.get_metrics(),
            }
        
        return workload
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system-wide metrics."""
        # Calculate averages
        if self.system_metrics["completed_sessions"] > 0:
            completed = self.system_metrics["completed_sessions"]
            self.system_metrics["escalation_rate"] = (
                self.system_metrics["total_escalations"] / completed
            )
        
        return {
            **self.system_metrics,
            "agent_count": len(self.agents),
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def get_session_distribution(self) -> Dict[str, int]:
        """Get distribution of sessions by agent type."""
        distribution = defaultdict(int)
        
        async with self._lock:
            for session in self.active_sessions.values():
                if session.current_agent_type:
                    distribution[session.current_agent_type] += 1
        
        return dict(distribution)
    
    async def _cleanup_loop(self):
        """Background task to clean up abandoned sessions."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                
                async with self._lock:
                    abandoned_sessions = []
                    current_time = datetime.utcnow()
                    
                    for session_id, session in self.active_sessions.items():
                        # Check if session has been inactive for too long
                        if session.updated_at < current_time - timedelta(minutes=30):
                            abandoned_sessions.append(session_id)
                    
                    # Clean up abandoned sessions
                    for session_id in abandoned_sessions:
                        session = self.active_sessions[session_id]
                        session.status = SessionStatus.ABANDONED
                        await self.release_session(session_id)
                        
                        logger.info(
                            "session_abandoned",
                            session_id=session_id,
                            last_activity=session.updated_at.isoformat()
                        )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cleanup_loop_error", error=str(e))
    
    async def _metrics_aggregation_loop(self):
        """Background task to aggregate metrics."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                
                # Aggregate agent metrics
                total_requests = 0
                total_successful = 0
                total_response_time = 0.0
                
                for agent in self.agents.values():
                    metrics = agent.get_metrics()
                    total_requests += metrics["total_requests"]
                    total_successful += metrics["successful_responses"]
                    
                    if metrics["successful_responses"] > 0:
                        total_response_time += (
                            metrics["average_response_time"] *
                            metrics["successful_responses"]
                        )
                
                # Update system metrics
                if total_successful > 0:
                    avg_response_time = total_response_time / total_successful
                    logger.info(
                        "metrics_aggregated",
                        total_requests=total_requests,
                        total_successful=total_successful,
                        average_response_time=avg_response_time
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("metrics_aggregation_error", error=str(e))
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform system health check."""
        agent_health = {}
        
        # Check each agent
        for agent_id, agent in self.agents.items():
            agent_health[agent_id] = await agent.health_check()
        
        # Overall system health
        unhealthy_agents = [
            aid for aid, health in agent_health.items()
            if health["status"] != "healthy"
        ]
        
        system_status = "healthy" if not unhealthy_agents else "degraded"
        
        return {
            "status": system_status,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": self.get_system_metrics(),
            "agent_health": agent_health,
            "unhealthy_agents": unhealthy_agents,
        }