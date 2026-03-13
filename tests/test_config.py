"""
Unit tests for core configuration module.
"""
import pytest
from unittest.mock import patch, MagicMock
import os
import importlib

import core.config as config_module


@pytest.mark.unit
class TestBotConfig:
    """Test suite for BotConfig class."""
    
    def test_config_loads_from_env(self):
        """Test that BotConfig loads from environment variables."""
        with patch.dict(os.environ, {
            'DISCORD_TOKEN': 'test_discord_token',
            'GEMINI_API_KEY': 'test_gemini_key',
            'AZURE_TENANT_ID': 'test_tenant',
            'AZURE_CLIENT_ID': 'test_client',
            'AZURE_CLIENT_SECRET': 'test_secret',
        }, clear=False):
            importlib.reload(config_module)
            BotConfig = config_module.BotConfig
            
            # Should load from environment
            assert BotConfig.DISCORD_TOKEN == 'test_discord_token'
            assert BotConfig.GEMINI_API_KEY == 'test_gemini_key'
    
    def test_config_has_required_constants(self):
        """Test that BotConfig has all required constants."""
        from core.config import BotConfig
        
        # Check file paths exist
        assert hasattr(BotConfig, 'BIRTHDAY_FILE')
        assert hasattr(BotConfig, 'VOICE_STATS_FILE')
        assert hasattr(BotConfig, 'COMPETITORS_FILE')
        
        # Check Discord IDs exist
        assert hasattr(BotConfig, 'BIRTHDAY_CHANNEL_ID')
        assert hasattr(BotConfig, 'GENERAL_CHANNEL_ID')
        
        # Check lists exist
        assert hasattr(BotConfig, 'RANK_ROLE_IDS')
        assert hasattr(BotConfig, 'BIRTHDAY_WISHES')
        assert isinstance(BotConfig.BIRTHDAY_WISHES, list)
