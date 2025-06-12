#!/usr/bin/env python3
"""
Demo script for Multi-Agent Customer Service System
Demonstrates various conversation scenarios and agent interactions
"""

import asyncio
import httpx
import json
from typing import Dict, Any
from datetime import datetime
import random

API_BASE_URL = "http://localhost:8000/api/v1"


class DemoScenario:
    """Base class for demo scenarios"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.session_id = None
        self.messages = []
    
    async def run(self, client: httpx.AsyncClient):
        """Run the demo scenario"""
        print(f"\n{'='*60}")
        print(f"Scenario: {self.name}")
        print(f"Description: {self.description}")
        print('='*60)
        
        # Create session
        await self.create_session(client)
        
        # Run conversation
        await self.conversation(client)
        
        # End session
        await self.end_session(client)
        
        # Show analytics
        await self.show_analytics(client)
    
    async def create_session(self, client: httpx.AsyncClient):
        """Create a new session"""
        response = await client.post(
            f"{API_BASE_URL}/sessions",
            json={"customer_id": f"demo_{random.randint(1000, 9999)}"}
        )
        data = response.json()
        self.session_id = data["session_id"]
        print(f"\n✅ Session created: {self.session_id}")
        print(f"   Agent: {data['agent_type']}")
    
    async def send_message(self, client: httpx.AsyncClient, message: str):
        """Send a message and display response"""
        print(f"\n👤 Customer: {message}")
        
        response = await client.post(
            f"{API_BASE_URL}/sessions/{self.session_id}/messages",
            json={"content": message}
        )
        data = response.json()
        
        print(f"🤖 {data['agent_type']}: {data['content']}")
        
        if data.get("escalated"):
            print("   ⚡ Conversation escalated to specialist")
        
        self.messages.append({
            "user": message,
            "agent": data["content"],
            "agent_type": data["agent_type"]
        })
        
        # Simulate thinking time
        await asyncio.sleep(1)
        
        return data
    
    async def end_session(self, client: httpx.AsyncClient, satisfaction: float = 8.0):
        """End the session with satisfaction score"""
        response = await client.post(
            f"{API_BASE_URL}/sessions/{self.session_id}/end",
            json={
                "satisfaction_score": satisfaction,
                "resolution_status": "resolved"
            }
        )
        print(f"\n✅ Session ended with satisfaction score: {satisfaction}/10")
    
    async def show_analytics(self, client: httpx.AsyncClient):
        """Show session analytics"""
        response = await client.get(f"{API_BASE_URL}/sessions/{self.session_id}")
        data = response.json()
        
        print(f"\n📊 Session Analytics:")
        print(f"   Total messages: {data['total_messages']}")
        print(f"   Escalations: {data['escalation_count']}")
        print(f"   Agents involved: {len(set(m['agent_type'] for m in self.messages))}")
        print(f"   Tags: {', '.join(data['tags'])}")
    
    async def conversation(self, client: httpx.AsyncClient):
        """Override this method in subclasses"""
        raise NotImplementedError


class TechnicalSupportScenario(DemoScenario):
    """Technical support scenario with escalation"""
    
    def __init__(self):
        super().__init__(
            "Technical Support Issue",
            "Customer experiences software crash, gets routed to technical support"
        )
    
    async def conversation(self, client: httpx.AsyncClient):
        await self.send_message(client, "Hi, I need help with your software")
        await self.send_message(client, "The application keeps crashing when I try to export data")
        await self.send_message(client, "I get an error code: EX-500")
        await self.send_message(client, "I've tried restarting but it's still not working")
        await self.send_message(client, "This is affecting our entire team's productivity")


class SalesInquiryScenario(DemoScenario):
    """Sales inquiry scenario"""
    
    def __init__(self):
        super().__init__(
            "Enterprise Sales Inquiry",
            "Large company inquiring about pricing and features"
        )
    
    async def conversation(self, client: httpx.AsyncClient):
        await self.send_message(client, "Hello, I'm interested in your enterprise solution")
        await self.send_message(client, "We're a Fortune 500 company with 10,000 employees")
        await self.send_message(client, "What's your pricing for large organizations?")
        await self.send_message(client, "Do you offer volume discounts?")
        await self.send_message(client, "We'd also need API integration with our existing systems")


class FrustratedCustomerScenario(DemoScenario):
    """Frustrated customer requiring supervisor escalation"""
    
    def __init__(self):
        super().__init__(
            "Frustrated Customer",
            "Customer is upset and requests to speak with a manager"
        )
    
    async def conversation(self, client: httpx.AsyncClient):
        await self.send_message(client, "This is absolutely unacceptable!")
        await self.send_message(client, "I've been having issues for weeks now")
        await self.send_message(client, "I want to speak to a manager immediately")
        await self.send_message(client, "I'm considering switching to your competitor")
        
    async def end_session(self, client: httpx.AsyncClient, satisfaction: float = 4.0):
        """Override with lower satisfaction"""
        await super().end_session(client, satisfaction)


class MixedInquiryScenario(DemoScenario):
    """Complex scenario with multiple escalations"""
    
    def __init__(self):
        super().__init__(
            "Mixed Technical and Sales Inquiry",
            "Customer with both technical questions and purchasing interest"
        )
    
    async def conversation(self, client: httpx.AsyncClient):
        await self.send_message(client, "Hi, I'm evaluating your product")
        await self.send_message(client, "First, I have some technical questions")
        await self.send_message(client, "Does your API support webhook notifications?")
        await self.send_message(client, "What's the rate limit for API calls?")
        await self.send_message(client, "Now, about pricing - what's the cost for 50 users?")
        await self.send_message(client, "Do you have a free trial available?")


async def show_system_metrics(client: httpx.AsyncClient):
    """Display system metrics"""
    response = await client.get(f"{API_BASE_URL}/system/metrics")
    metrics = response.json()
    
    print(f"\n{'='*60}")
    print("System Metrics")
    print('='*60)
    print(f"Total sessions: {metrics['total_sessions']}")
    print(f"Active sessions: {metrics['active_sessions']}")
    print(f"Completed sessions: {metrics['completed_sessions']}")
    print(f"Total escalations: {metrics['total_escalations']}")
    print(f"\nAgent Workload:")
    
    for agent_id, workload in metrics['agent_workload'].items():
        print(f"  {agent_id}: {workload['current_load']} sessions")


async def run_demo():
    """Run all demo scenarios"""
    print("🚀 Multi-Agent Customer Service System Demo")
    print("=" * 60)
    
    scenarios = [
        TechnicalSupportScenario(),
        SalesInquiryScenario(),
        FrustratedCustomerScenario(),
        MixedInquiryScenario(),
    ]
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check system health
        try:
            response = await client.get(f"{API_BASE_URL}/system/health")
            if response.json()["status"] != "healthy":
                print("❌ System is not healthy. Please check the services.")
                return
        except Exception as e:
            print(f"❌ Cannot connect to API: {e}")
            print("Make sure the service is running (docker-compose up)")
            return
        
        print("✅ System is healthy and ready")
        
        # Run scenarios
        for scenario in scenarios:
            await scenario.run(client)
            await asyncio.sleep(2)  # Pause between scenarios
        
        # Show final metrics
        await show_system_metrics(client)
    
    print(f"\n{'='*60}")
    print("Demo completed successfully!")
    print("Check Grafana dashboards at http://localhost:3000 for visualizations")


if __name__ == "__main__":
    asyncio.run(run_demo())