"""
Rate limiting utilities for Beanie Bot.
Prevents spam and abuse of commands.
"""

from datetime import datetime, timedelta
from typing import Dict, Tuple
import logging


class RateLimiter:
    """
    In-memory rate limiter using sliding window approach.
    
    Thread-safe for use across async tasks.
    """
    
    def __init__(self, max_calls: int, period_seconds: int, name: str = "RateLimiter"):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum calls allowed per period
            period_seconds: Time window in seconds
            name: Name for logging
        """
        self.max_calls = max_calls
        self.period = timedelta(seconds=period_seconds)
        self.calls: Dict[int, list] = {}
        self.name = name
        logging.info(f"Rate limiter '{name}' initialized: {max_calls} calls per {period_seconds}s")
    
    def is_allowed(self, user_id: int) -> Tuple[bool, float]:
        """
        Check if user is allowed to make a call.
        
        Args:
            user_id: Discord user ID
        
        Returns:
            (is_allowed, wait_seconds_if_not_allowed)
            - If allowed: (True, 0.0)
            - If limited: (False, seconds_to_wait)
        """
        now = datetime.utcnow()
        window_start = now - self.period
        
        # Initialize user tracking if needed
        if user_id not in self.calls:
            self.calls[user_id] = []
        
        # Remove old calls outside window (sliding window)
        self.calls[user_id] = [
            ts for ts in self.calls[user_id] if ts > window_start
        ]
        
        # Check if under limit
        if len(self.calls[user_id]) < self.max_calls:
            self.calls[user_id].append(now)
            logging.debug(f"Rate limiter '{self.name}': User {user_id} allowed " +
                        f"({len(self.calls[user_id])}/{self.max_calls} calls in window)")
            return True, 0.0
        
        # Calculate wait time until oldest call exits window
        oldest_call = self.calls[user_id][0]
        wait_until = oldest_call + self.period
        wait_seconds = (wait_until - now).total_seconds()
        
        logging.warning(f"Rate limiter '{self.name}': User {user_id} rate limited " +
                       f"(wait {wait_seconds:.1f}s)")
        return False, max(0, wait_seconds)
    
    def reset_user(self, user_id: int):
        """Clear rate limit history for a user (e.g., admin bypass)."""
        if user_id in self.calls:
            del self.calls[user_id]
            logging.info(f"Rate limiter '{self.name}': Reset for user {user_id}")
    
    def cleanup_old_users(self):
        """Remove entries for users with no recent calls. Call periodically to clean up memory."""
        now = datetime.utcnow()
        window_start = now - self.period
        
        to_remove = []
        for user_id, calls in self.calls.items():
            active_calls = [ts for ts in calls if ts > window_start]
            if not active_calls:
                to_remove.append(user_id)
        
        for user_id in to_remove:
            del self.calls[user_id]
        
        if to_remove:
            logging.debug(f"Rate limiter '{self.name}': Cleaned up {len(to_remove)} inactive users")


class GlobalRateLimiter:
    """
    Multi-purpose rate limiter for different command types.
    Each command type can have different limits.
    """
    
    def __init__(self):
        self.limiters: Dict[str, RateLimiter] = {}
    
    def get_limiter(self, limiter_name: str, max_calls: int = 10, 
                   period_seconds: int = 60) -> RateLimiter:
        """
        Get or create a rate limiter by name.
        
        Args:
            limiter_name: Unique name for this rate limiter
            max_calls: Maximum calls (only used if creating new)
            period_seconds: Period in seconds (only used if creating new)
        
        Returns:
            RateLimiter instance
        """
        if limiter_name not in self.limiters:
            self.limiters[limiter_name] = RateLimiter(max_calls, period_seconds, limiter_name)
        return self.limiters[limiter_name]
    
    def is_allowed(self, limiter_name: str, user_id: int) -> Tuple[bool, float]:
        """Check if user is allowed under the named limiter."""
        limiter = self.get_limiter(limiter_name)
        return limiter.is_allowed(user_id)
