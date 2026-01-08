"""
Global rate limiter instance for SlowAPI.

This module exports a single limiter instance to avoid circular imports.
All rate limiting decorators should import from this module.
"""

from slowapi import Limiter
from app.utils.rate_limit import get_rate_limit_key

# Create global limiter instance with default memory storage
# Uses get_rate_limit_key to determine rate limit keys (user-based or IP-based)
limiter = Limiter(key_func=get_rate_limit_key)
