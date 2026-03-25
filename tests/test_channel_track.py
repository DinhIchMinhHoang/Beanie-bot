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
        assert channel_feature.channel_occupancy == {}
    
    def test_get_period_key(self, channel_feature, mock_config):
        """Test period key generation."""
        period = channel_feature._get_period_key()
        assert period is not None
        assert len(period.split('-')) == 2  # YYYY-MM format
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_channel_becomes_occupied(self, channel_feature, mock_bot):
        """Test when first user joins a tracked channel (0→1 occupancy)."""
        channel_id = 789012345
        
        # Mock before: channel empty
        mock_before = MagicMock()
        mock_before.channel = None
        
        # Mock after: user in channel
        mock_after = MagicMock()
        mock_after.channel = MagicMock(spec=discord.VoiceChannel)
        mock_after.channel.id = channel_id
        
        mock_member = MagicMock()
        mock_member.guild.id = TEST_GUILD_ID
        mock_member.id = 123456
        
        # Mock storage and occupancy check (occupancy will be 1)
        storage = MagicMock()
        storage.load_tracked_channels.return_value = [channel_id]
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            with patch.object(channel_feature, '_get_channel_occupancy', return_value=1):
                await channel_feature.on_voice_state_update(mock_member, mock_before, mock_after)
        
        # Should mark channel as occupied and record start time
        channel_occupancy = channel_feature.channel_occupancy.get(channel_id)
        assert channel_occupancy is not None
        assert channel_occupancy["is_occupied"] is True
        assert channel_occupancy["occupy_start_time"] is not None
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_channel_becomes_empty(self, channel_feature, mock_bot):
        """Test when last user leaves a tracked channel (1→0 occupancy)."""
        import time
        channel_id = 789012345
        
        # Set up: channel was occupied
        start_time = time.time() - 100  # 100 seconds ago
        channel_feature.channel_occupancy[channel_id] = {
            "is_occupied": True,
            "occupy_start_time": start_time
        }
        
        # Mock before: user was in channel
        mock_before = MagicMock()
        mock_before.channel = MagicMock(spec=discord.VoiceChannel)
        mock_before.channel.id = channel_id
        
        # Mock after: user left
        mock_after = MagicMock()
        mock_after.channel = None
        
        mock_member = MagicMock()
        mock_member.guild.id = TEST_GUILD_ID
        
        # Mock storage
        storage = MagicMock()
        storage.load_tracked_channels.return_value = [channel_id]
        storage.add_to_channel_stats = MagicMock()
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            with patch.object(channel_feature, '_get_channel_occupancy', return_value=0):
                with patch.object(channel_feature, '_get_period_key', return_value='2026-03'):
                    await channel_feature.on_voice_state_update(mock_member, mock_before, mock_after)
        
        # Should have recorded the uptime duration
        storage.add_to_channel_stats.assert_called_once()
        call_args = storage.add_to_channel_stats.call_args
        assert call_args[0][0] == TEST_GUILD_ID
        assert call_args[0][1] == channel_id
        assert call_args[0][2] == '2026-03'
        assert call_args[0][3] >= 100  # duration should be ~100 seconds
        
        # Channel should be marked as not occupied
        assert channel_feature.channel_occupancy[channel_id]["is_occupied"] is False
    
    @pytest.mark.asyncio
    async def test_on_guild_channel_delete(self, channel_feature):
        """Test cleanup when a tracked channel is deleted."""
        channel_id = 789012345
        
        mock_channel = MagicMock(spec=discord.VoiceChannel)
        mock_channel.guild.id = TEST_GUILD_ID
        mock_channel.id = channel_id
        
        # Add channel to occupancy state
        channel_feature.channel_occupancy[channel_id] = {
            "is_occupied": False,
            "occupy_start_time": None
        }
        
        # Mock storage
        storage = MagicMock()
        storage.remove_tracked_channel = MagicMock()
        
        with patch.object(channel_feature, '_get_storage', return_value=storage):
            await channel_feature.on_guild_channel_delete(mock_channel)
        
        storage.remove_tracked_channel.assert_called_once_with(TEST_GUILD_ID, channel_id)
        assert channel_id not in channel_feature.channel_occupancy
