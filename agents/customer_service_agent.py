from typing import List, Dict
from agents.base_agent import BaseAgent


class CustomerServiceAgent(BaseAgent):
    """
    Gateway agent that handles initial customer contact and routes to specialists.
    Temperature: 0.3 for professional, consistent responses.
    """
    
    def __init__(self, **kwargs):
        # Set default temperature for customer service
        kwargs.setdefault('temperature', 0.3)
        kwargs.setdefault('agent_type', 'customer_service')
        super().__init__(**kwargs)
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for customer service agent."""
        return """You are a professional customer service representative for our company. 
Your role is to:

1. Greet customers warmly and professionally
2. Understand their needs through active listening
3. Provide general assistance and information
4. Route technical issues to technical support specialists
5. Route sales inquiries to sales specialists
6. Maintain a helpful and empathetic tone
7. Document key information about the customer's needs

Guidelines:
- Always be polite, professional, and patient
- Ask clarifying questions when needed
- Acknowledge customer concerns before providing solutions
- If you detect frustration, show empathy and offer to escalate
- Keep responses concise but informative
- Use the customer's name when provided

You should identify when to route conversations to:
- Technical Support: For product issues, bugs, troubleshooting
- Sales Specialist: For pricing, purchasing, product comparisons
- Supervisor: For complaints, escalated issues, or special requests

Remember: You are the first point of contact and set the tone for the entire interaction."""
    
    def _get_escalation_keywords(self) -> List[str]:
        """Keywords that might trigger escalation."""
        return [
            # Technical issues
            "not working", "broken", "error", "bug", "crash", 
            "technical", "problem", "issue", "troubleshoot",
            # Sales related
            "buy", "purchase", "price", "cost", "discount", 
            "quote", "proposal", "compare", "upgrade",
            # Escalation triggers
            "manager", "supervisor", "escalate", "complaint",
            "frustrated", "unacceptable", "terrible service"
        ]
    
    def _get_routing_rules(self) -> Dict[str, str]:
        """Define routing rules based on keywords."""
        return {
            # Technical support routing
            "not working": "technical_support",
            "broken": "technical_support",
            "error": "technical_support",
            "bug": "technical_support",
            "crash": "technical_support",
            "technical issue": "technical_support",
            "troubleshoot": "technical_support",
            "installation": "technical_support",
            "configuration": "technical_support",
            
            # Sales routing
            "buy": "sales_specialist",
            "purchase": "sales_specialist",
            "pricing": "sales_specialist",
            "cost": "sales_specialist",
            "discount": "sales_specialist",
            "quote": "sales_specialist",
            "proposal": "sales_specialist",
            "compare products": "sales_specialist",
            "upgrade": "sales_specialist",
            "subscription": "sales_specialist",
            "plan": "sales_specialist",
            
            # Supervisor routing
            "speak to manager": "supervisor",
            "supervisor": "supervisor",
            "escalate": "supervisor",
            "file complaint": "supervisor",
            "very frustrated": "supervisor",
            "legal": "supervisor",
            "lawsuit": "supervisor",
        }