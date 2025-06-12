from typing import List, Dict
from agents.base_agent import BaseAgent


class SalesSpecialistAgent(BaseAgent):
    """
    Sales specialist that handles pricing, product info, and sales processes.
    Temperature: 0.7 for creative, persuasive responses.
    """
    
    def __init__(self, **kwargs):
        # Set default temperature for creative sales responses
        kwargs.setdefault('temperature', 0.7)
        kwargs.setdefault('agent_type', 'sales_specialist')
        super().__init__(**kwargs)
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for sales specialist agent."""
        return """You are an experienced sales specialist with expertise in consultative selling and solution design.
Your role is to:

1. Understand customer needs and business requirements
2. Recommend appropriate products and solutions
3. Explain pricing, features, and value propositions
4. Handle objections professionally
5. Create compelling ROI justifications
6. Guide customers through the purchasing process

Sales Guidelines:
- Focus on value, not just features
- Use social proof and success stories
- Address concerns before they become objections
- Personalize recommendations based on customer needs
- Be enthusiastic but not pushy
- Always be transparent about pricing and terms

Key Areas:
- Product knowledge and comparisons
- Pricing structures and discounts
- Enterprise solutions and custom packages
- ROI calculations and business cases
- Competitive advantages
- Implementation timelines
- Support and service levels

Escalation Criteria:
- Enterprise deals > $50,000 → Account Manager
- Custom development requests → Solutions Architect
- Legal/contract questions → Legal team
- Technical integration details → Technical Sales Engineer

Sales Techniques:
- SPIN selling for discovery
- Feature-Advantage-Benefit presentations
- Challenger sales approach for thought leadership
- Solution selling for complex needs

Remember: Build trust, demonstrate value, and help customers make informed decisions."""
    
    def _get_escalation_keywords(self) -> List[str]:
        """Keywords that might trigger escalation."""
        return [
            # Account manager escalation
            "enterprise", "large company", "custom contract", "negotiate",
            "bulk discount", "multi-year", "sla", "dedicated support",
            # Solutions architect
            "custom development", "api integration", "special requirements",
            "modify product", "unique needs", "technical integration",
            # Legal team
            "contract terms", "legal", "liability", "compliance",
            "data privacy", "gdpr", "terms of service",
            # Back to support
            "technical issue", "not working", "bug", "error"
        ]
    
    def _get_routing_rules(self) -> Dict[str, str]:
        """Define routing rules based on keywords."""
        return {
            # Account manager routing
            "enterprise": "account_manager",
            "large company": "account_manager",
            "fortune 500": "account_manager",
            "custom contract": "account_manager",
            "bulk pricing": "account_manager",
            "negotiate": "account_manager",
            "multi-year deal": "account_manager",
            
            # Solutions architect routing
            "custom development": "solutions_architect",
            "api integration": "solutions_architect",
            "special requirements": "solutions_architect",
            "modify product": "solutions_architect",
            "technical integration": "technical_sales_engineer",
            
            # Legal routing
            "contract terms": "legal_team",
            "legal question": "legal_team",
            "liability": "legal_team",
            "compliance": "legal_team",
            "data privacy": "legal_team",
            
            # Back to support
            "technical issue": "technical_support",
            "not working": "technical_support",
            "bug": "technical_support",
            "implementation help": "technical_support",
        }