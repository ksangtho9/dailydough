"""
Rate limiting utilities for SlowAPI.

Provides key function that uses authenticated user when available,
falling back to IP address for unauthenticated requests.
"""

from fastapi import Request
from jose import jwt as jose_jwt
from slowapi.util import get_remote_address


def get_rate_limit_key(request: Request) -> str:
    """
    Generate a rate limit key for SlowAPI.

    Extracts the user identity directly from the JWT Authorization header so
    rate limits are per-user rather than per-IP for authenticated requests.
    Uses unverified claims — signature validation still happens in get_current_user.
    Falls back to IP for unauthenticated requests.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            claims = jose_jwt.get_unverified_claims(token)
            user_id = claims.get("email") or claims.get("sub")
            if user_id:
                return f"user:{user_id}"
        except Exception:
            pass

    return f"ip:{get_remote_address(request)}"
