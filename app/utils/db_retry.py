"""
Retry utility for database operations, specifically handling SQLite "database is locked" errors.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Callable, TypeVar, ParamSpec

from sqlalchemy import exc as sa_exc
import sqlite3

logger = logging.getLogger("bakezy.db_retry")

P = ParamSpec("P")
R = TypeVar("R")


def is_database_locked_error(exception: Exception) -> bool:
    """
    Check if an exception is a SQLite "database is locked" error.
    """
    if isinstance(exception, sa_exc.OperationalError):
        msg = str(exception.orig) if hasattr(exception, "orig") and exception.orig else str(exception)
        if "database is locked" in msg.lower():
            return True
    
    if isinstance(exception, sqlite3.OperationalError):
        msg = str(exception)
        if "database is locked" in msg.lower():
            return True
    
    return False


def retry_db_operation(
    max_retries: int = 5,
    initial_delay: float = 0.1,
    max_delay: float = 1.6,
    backoff_factor: float = 2.0,
):
    """
    Decorator to retry database operations on "database is locked" errors.
    
    Args:
        max_retries: Maximum number of retry attempts (default: 5)
        initial_delay: Initial delay in seconds before first retry (default: 0.1)
        max_delay: Maximum delay in seconds between retries (default: 1.6)
        backoff_factor: Multiplier for exponential backoff (default: 2.0)
    
    Returns:
        Decorated function that retries on database locked errors
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if not is_database_locked_error(e):
                        # Not a database locked error, re-raise immediately
                        raise
                    
                    last_exception = e
                    
                    if attempt < max_retries:
                        logger.warning(
                            f"Database locked error on attempt {attempt + 1}/{max_retries + 1} "
                            f"for {func.__name__}. Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        logger.error(
                            f"Database locked error after {max_retries + 1} attempts "
                            f"for {func.__name__}. Giving up."
                        )
                        raise
            
            # This should never be reached, but just in case
            if last_exception:
                raise last_exception
            
            raise RuntimeError("Unexpected error in retry_db_operation")
        
        return wrapper
    return decorator


