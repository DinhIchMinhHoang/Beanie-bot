"""
Unit tests for Channel Tracking feature module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord

from features.channel_track import ChannelTrackingFeature
from tests.conftest import TEST_GUILD_ID


@pytest.mark.unit
class TestChannelTrackingFeature:
    """Test suite for ChannelTrackingFeature cog."""
    
    @pytest.fixture
    def channel_feature(self, mock_bot, mock_config):
        """Create ChannelTrackingFeature instance with mocked dependencies."""
        with patch.multiple(
            ChannelTrackingFeature,
            update_channel_names=MagicMock(start=MagicMock(), cancel=MagicMock()),
            monthly_reset_check=MagicMock(start=MagicMock(), cancel=MagicMock()),
            checkpoint_channel_stats=MagicMock(start=MagicMock(), cancel=MagicMock())
        ):
            with patch('asyncio.create_task', return_value=AsyncMock()):
                feature = ChannelTrackingFeature(mock_bot, mock_config)
        return feature
    
    def test_initialization(self, channel_feature, mock_bot, mock_config):
        """Test that ChannelTrackingFeature initializes correctly."""
        assert channel_feature.bot == mock_bot
        assert channel_feature.config == mock_config
        assert channel_feature.channel_user_times == {}
    
    def test_get_period_key(self, channel_feature, mock_config):
        """Test period key generation."""
        period = channel_feature._get_period_key()
        assert period is not None
        assert len(period.split('-')) == 2  # YYYY-MM format
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_user_joins(self, channel_feature, mock_bot):
        """Test tracking when user joins a tracked channel."""
        user_id_str = "123456"
        channel_id = 789012345
        
        # Mock members and channels
        mock_before = MagicMock()
        mock_before.channel = None
        
        mock_after = MagicMock()
        mock_after.channel = MagicMock(spec=discord.VoiceChannel)
        mock_after.channel.id = channel_id
        
        mock_member = MagicMock()
        mock_member.guild.id = TEST_GUILD_ID
        mock_member.id = int(user_id_str)
        
        # Mock storage
        storage = MagicMock()
        storage.load_tracked_channels.return_value = [channel_id]
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            await channel_feature.on_voice_state_update(mock_member, mock_before, mock_after)
        
        # Should add user to channel tracking
        assert user_id_str in channel_feature.channel_user_times.get(channel_id, {})
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_user_leaves(self, channel_feature, mock_bot):
        """Test recording time when user leaves tracked channel."""
        import time
        user_id_str = "123456"
        channel_id = 789012345
        
        # Set up initial state - user in channel
        channel_feature.channel_user_times[channel_id] = {user_id_str: time.time() - 100}  # 100 sec ago
        
        # Mock members and channels
        mock_before = MagicMock()
        mock_before.channel = MagicMock(spec=discord.VoiceChannel)
        mock_before.channel.id = channel_id
        
        mock_after = MagicMock()
        mock_after.channel = None  # User left
        
        mock_member = MagicMock()
        mock_member.guild.id = TEST_GUILD_ID
        mock_member.id = int(user_id_str)
        
        # Mock storage
        storage = MagicMock()
        storage.load_tracked_channels.return_value = [channel_id]
        storage.add_to_channel_stats = MagicMock()
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            with patch.object(channel_feature, '_get_period_key', return_value='2026-03'):
                await channel_feature.on_voice_state_update(mock_member, mock_before, mock_after)
        
        # Should have recorded time
        storage.add_to_channel_stats.assert_called_once()
        assert user_id_str not in channel_feature.channel_user_times.get(channel_id, {})
    
    @pytest.mark.asyncio
    async def test_on_guild_channel_delete(self, channel_feature):
        """Test cleanup when a tracked channel is deleted."""
        channel_id = 789012345
        
        mock_channel = MagicMock(spec=discord.VoiceChannel)
        mock_channel.guild.id = TEST_GUILD_ID
        mock_channel.id = channel_id
        
        # Add channel to RAM state
        channel_feature.channel_user_times[channel_id] = {"user1": 100}
        
        # Mock storage
        storage = MagicMock()
        storage.remove_tracked_channel = MagicMock()
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            await channel_feature.on_guild_channel_delete(mock_channel)
        
        storage.remove_tracked_channel.assert_called_once_with(TEST_GUILD_ID, channel_id)
        assert channel_id not in channel_feature.channel_user_times
