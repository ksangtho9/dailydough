from __future__ import annotations

import os
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.api.auth import get_current_user
from app.models import Bakery
from app.services.ai_context_builder import build_bakery_context, format_context_for_prompt

router = APIRouter(tags=["ai-assistant"])


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    response: str
    context_used: bool = True


def call_openai_api(
    system_prompt: str,
    user_message: str,
    conversation_history: Optional[List[ChatMessage]] = None,
) -> str:
    """
    Call OpenAI API to get AI response.
    Falls back to a simple response if API key is not configured.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Fallback response when API key is not configured
        return (
            "I'm your bakery planning assistant, but I need to be configured with an OpenAI API key to provide intelligent responses. "
            "Please set the OPENAI_API_KEY environment variable. "
            "For now, I can tell you that I have access to your bakery's forecast data, sales history, and top products. "
            "What would you like to know about your bakery operations?"
        )

    try:
        import httpx

        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history[-10:]:  # Limit to last 10 messages
                messages.append({"role": msg.role, "content": msg.content})
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})

        # Call OpenAI API
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000,
            },
            timeout=30.0,
        )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")

        data = response.json()
        return data["choices"][0]["message"]["content"]

    except ImportError:
        return (
            "The httpx library is required for AI functionality. "
            "Please install it with: pip install httpx"
        )
    except Exception as e:
        return f"I encountered an error: {str(e)}. Please check your API configuration."


@router.post(
    "/bakeries/{bakery_id}/ai-assistant/chat",
    response_model=ChatResponse,
)
def chat_with_ai(
    bakery_id: int,
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Chat with AI assistant about bakery forecasts and planning.
    The AI has access to current bakery data including forecasts, sales, and metrics.
    """
    # Verify bakery exists
    bakery = db.query(Bakery).filter(Bakery.id == bakery_id).first()
    if not bakery:
        raise HTTPException(status_code=404, detail="Bakery not found")

    # Build context
    context = build_bakery_context(bakery_id, db)
    context_text = format_context_for_prompt(context)

    # Build system prompt
    system_prompt = f"""You are an AI assistant helping a bakery owner with demand forecasting and planning decisions.

You have access to the following bakery data:

{context_text}

Your role is to:
- Answer questions about forecasts, sales trends, and bakery operations
- Provide insights and recommendations based on the data
- Help with scenario planning (e.g., "what if it rains?", "what if there's a holiday?")
- Generate summaries of key metrics and trends
- Be concise, helpful, and data-driven in your responses

Always base your answers on the provided data. If you don't have specific data, say so rather than guessing.
Use natural, conversational language."""

    # Get AI response
    response_text = call_openai_api(
        system_prompt=system_prompt,
        user_message=request.message,
        conversation_history=request.conversation_history,
    )

    return ChatResponse(
        response=response_text,
        context_used=True,
    )







