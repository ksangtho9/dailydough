"""
Rate limiting utilities for SlowAPI.

Provides key function that uses authenticated user when available,
falling back to IP address for unauthenticated requests.
"""

from fastapi import Request
from slowapi.util import get_remote_address


def get_rate_limit_key(request: Request) -> str:
    """
    Generate a rate limit key for SlowAPI.
    
    Uses authenticated user email/ID if available, otherwise falls back to IP address.
    Returns keys in format 'user:<value>' or 'ip:<value>'.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Rate limit key string
    """
    # Check if user is authenticated and stored in request state
    if hasattr(request.state, "user") and request.state.user is not None:
        user = request.state.user
        # Prefer email if available, otherwise use ID
        user_identifier = getattr(user, "email", None) or getattr(user, "id", None)
        if user_identifier is not None:
            return f"user:{user_identifier}"
    
    # Fallback to IP address for unauthenticated requests
    ip_address = get_remote_address(request)
    return f"ip:{ip_address}"
