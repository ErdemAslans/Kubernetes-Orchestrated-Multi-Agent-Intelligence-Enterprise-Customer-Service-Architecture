from typing import List, Dict
from agents.base_agent import BaseAgent


class TechnicalSupportAgent(BaseAgent):
    """
    Technical support specialist that troubleshoots issues and provides solutions.
    Temperature: 0.2 for technical accuracy priority.
    """
    
    def __init__(self, **kwargs):
        # Set default temperature for technical accuracy
        kwargs.setdefault('temperature', 0.2)
        kwargs.setdefault('agent_type', 'technical_support')
        super().__init__(**kwargs)
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for technical support agent."""
        return """You are an expert technical support specialist with deep knowledge of our products and systems.
Your role is to:

1. Diagnose technical issues systematically
2. Provide clear, step-by-step troubleshooting instructions
3. Document issues for potential bug reports
4. Escalate complex system issues to development teams
5. Educate users on proper product usage

Technical Guidelines:
- Always start with basic troubleshooting (restart, update, etc.)
- Ask specific diagnostic questions
- Provide numbered steps for clarity
- Use technical terms but explain them when necessary
- Verify each step is completed before moving to the next
- Document error messages and symptoms precisely

Knowledge Areas:
- Software installation and configuration
- Common error codes and their solutions
- System requirements and compatibility
- Integration with third-party systems
- Performance optimization
- Security best practices

Escalation Criteria:
- System-wide outages → Development team
- Data loss or corruption → Senior technical specialist
- Security breaches → Security team
- Unresolved after 3 troubleshooting attempts → Senior support

Remember: Be patient, thorough, and ensure the customer understands each step."""
    
    def _get_escalation_keywords(self) -> List[str]:
        """Keywords that might trigger escalation."""
        return [
            # Development team escalation
            "system down", "outage", "all users affected", "critical bug",
            "data corruption", "security breach", "vulnerability",
            # Senior support escalation  
            "still not working", "tried everything", "urgent", "production down",
            "data loss", "cannot access", "completely broken",
            # Back to customer service
            "refund", "cancel", "pricing", "sales", "discount"
        ]
    
    def _get_routing_rules(self) -> Dict[str, str]:
        """Define routing rules based on keywords."""
        return {
            # Development team routing
            "system down": "development_team",
            "outage": "development_team",
            "all users affected": "development_team",
            "critical bug": "development_team",
            "data corruption": "development_team",
            "security breach": "security_team",
            "vulnerability": "security_team",
            
            # Senior technical support
            "still not working": "senior_technical_support",
            "tried everything": "senior_technical_support",
            "production down": "senior_technical_support",
            "data loss": "senior_technical_support",
            
            # Back to other departments
            "refund": "customer_service",
            "cancel subscription": "customer_service",
            "pricing": "sales_specialist",
            "upgrade": "sales_specialist",
            "different product": "sales_specialist",
        }