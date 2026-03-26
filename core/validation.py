"""
Input validation utilities for Beanie Bot.
Provides centralized validation for all user inputs.
"""

import re
from typing import Tuple, Any


class Validator:
    """Input validation utilities."""
    
    @staticmethod
    def validate_message(message: str, max_length: int = 500) -> Tuple[bool, str]:
        """
        Validate chat message.
        
        Returns: (is_valid, error_message)
        """
        if not message or len(message.strip()) == 0:
            return False, "Message cannot be empty"
        
        if len(message) > max_length:
            return False, f"Message too long (max {max_length} characters)"
        
        # Check for common injection patterns (SQL, command injection)
        dangerous_patterns = [
            r"'\s*OR\s*'",  # SQL injection
            r"--\s*$",       # SQL comment
            r"DROP\s+",      # SQL DROP
            r"DELETE\s+",    # SQL DELETE
            r"INSERT\s+",    # SQL INSERT
            r"UPDATE\s+",    # SQL UPDATE
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, message.upper()):
                return False, "Invalid message content (potential injection detected)"
        
        return True, ""
    
    @staticmethod
    def validate_discord_id(id_value: Any) -> Tuple[bool, int]:
        """
        Validate Discord ID format.
        Discord IDs are positive integers within uint64 range.
        
        Returns: (is_valid, id_as_int)
        """
        try:
            id_int = int(id_value)
            if id_int <= 0 or id_int > 2**63 - 1:  # Discord uses uint64
                return False, 0
            return True, id_int
        except (ValueError, TypeError):
            return False, 0
    
    @staticmethod
    def validate_date_ddmm(date_str: str) -> Tuple[bool, str]:
        """
        Validate birthday in dd/mm format.
        
        Returns: (is_valid, normalized_date)
        """
        if not date_str or not isinstance(date_str, str):
            return False, ""
        
        match = re.match(r'^(\d{2})/(\d{2})$', date_str.strip())
        if not match:
            return False, ""
        
        day, month = int(match.group(1)), int(match.group(2))
        
        # Validate logical ranges
        if not (1 <= day <= 31) or not (1 <= month <= 12):
            return False, ""
        
        # Extra validation: Feb 30-31, Apr 31, Jun 31, Sep 31, Nov 31 don't exist
        days_in_month = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if day > days_in_month[month - 1]:
            return False, ""
        
        return True, f"{day:02d}/{month:02d}"
    
    @staticmethod
    def validate_channel_id(channel_id: Any) -> Tuple[bool, int]:
        """Validate channel ID."""
        return Validator.validate_discord_id(channel_id)
    
    @staticmethod
    def validate_user_id(user_id: Any) -> Tuple[bool, int]:
        """Validate user ID."""
        return Validator.validate_discord_id(user_id)
    
    @staticmethod
    def validate_username(username: str, max_length: int = 100) -> Tuple[bool, str]:
        """
        Validate username format.
        
        Returns: (is_valid, sanitized_username)
        """
        if not username or len(username.strip()) == 0:
            return False, ""
        
        if len(username) > max_length:
            return False, ""
        
        # Allow alphanumeric, spaces, underscores, hyphens, periods
        if not re.match(r'^[a-zA-Z0-9\s_\-\.]+$', username):
            return False, ""
        
        return True, username.strip()
    
    @staticmethod
    def validate_action(action: str, valid_actions: list) -> Tuple[bool, str]:
        """
        Validate that action is one of allowed values.
        
        Args:
            action: The action string to validate
            valid_actions: List of valid action strings (case-insensitive)
        
        Returns: (is_valid, normalized_action)
        """
        if not action or not isinstance(action, str):
            return False, ""
        
        action_lower = action.lower()
        
        for valid_action in valid_actions:
            if action_lower == valid_action.lower():
                return True, valid_action.lower()
        
        return False, ""
    
    @staticmethod
    def validate_int_range(value: Any, min_val: int, max_val: int) -> Tuple[bool, int]:
        """
        Validate integer is within range.
        
        Returns: (is_valid, value_as_int)
        """
        try:
            int_val = int(value)
            if min_val <= int_val <= max_val:
                return True, int_val
            return False, 0
        except (ValueError, TypeError):
            return False, 0
