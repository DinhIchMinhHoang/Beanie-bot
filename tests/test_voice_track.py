"""
Unit tests for Voice Tracking feature module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import json

from features.voice_track import VoiceTrackingFeature
from tests.conftest import TEST_GUILD_ID


@pytest.mark.unit
class TestVoiceTrackingFeature:
    """Test suite for VoiceTrackingFeature cog."""
    
    @pytest.fixture
    def voice_feature(self, mock_bot, mock_config):
        """Create VoiceTrackingFeature instance with mocked dependencies."""
        # Patch all task loops and async task creation to prevent them from starting
        with patch.multiple(
            VoiceTrackingFeature,
            update_leaderboard=MagicMock(start=MagicMock(), cancel=MagicMock()),
            monthly_reset_check=MagicMock(start=MagicMock(), cancel=MagicMock()),
            periodic_role_sync=MagicMock(start=MagicMock(), cancel=MagicMock())
        ):
            with patch('asyncio.create_task', return_value=AsyncMock()):
                feature = VoiceTrackingFeature(mock_bot, "ffmpeg", mock_config)
        return feature
    
    def test_initialization(self, voice_feature, mock_bot, mock_config):
        """Test that VoiceTrackingFeature initializes correctly."""
        assert voice_feature.bot == mock_bot
        assert voice_feature.config == mock_config
        assert voice_feature.ffmpeg_exec == "ffmpeg"
        assert voice_feature.voice_join_times == {}
    
    def test_load_voice_stats_empty(self, voice_feature):  
        """Test loading voice stats when file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            result = voice_feature.load_voice_stats(TEST_GUILD_ID)
            assert result == {}
    
    def test_load_voice_stats_with_data(self, voice_feature):
        """Test loading voice stats from existing file."""
        test_data = {"123456": 3600, "789012": 7200}  # 1h and 2h in seconds
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.getsize', return_value=100):
                with patch('builtins.open', mock_open(read_data=json.dumps(test_data))):
                    result = voice_feature.load_voice_stats(TEST_GUILD_ID)
                    assert result == test_data
    
    def test_load_voice_stats_migration_old_format(self, voice_feature):
        """Test auto-migration from old format {user: {total: X}} to new {user: X}."""
        old_format = {"123456": {"total": 3600, "monthly": 1800}}
        expected = {"123456": 3600}
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.getsize', return_value=100):
                with patch('builtins.open', mock_open(read_data=json.dumps(old_format))):
                    result = voice_feature.load_voice_stats(TEST_GUILD_ID)
                    assert result == expected
    
    def test_save_voice_stats(self, voice_feature, mock_config):
        """Test saving voice stats to file atomically."""
        test_data = {"123456": 3600}
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)
        
        m = mock_open()
        with patch('builtins.open', m):
            with patch('os.replace'):
                voice_feature.save_voice_stats(TEST_GUILD_ID, test_data)
        
        # Should write to temp file first
        m.assert_called_once()
        assert '.tmp' in m.call_args[0][0]
    
    def test_get_user_rank_iron(self, voice_feature):
        """Test rank calculation for Iron (< 10h)."""
        rank_name, role_id, perks = voice_feature.get_user_rank(5)
        assert rank_name == "Iron"
        assert perks == []
    
    def test_get_user_rank_gold(self, voice_feature):
        """Test rank calculation for Gold (30-40h)."""
        rank_name, role_id, perks = voice_feature.get_user_rank(35)
        assert rank_name == "Gold"
        assert "/say" in perks
    
    def test_get_user_rank_legendary(self, voice_feature):
        """Test rank calculation for Legendary (80+ h)."""
        rank_name, role_id, perks = voice_feature.get_user_rank(100)
        assert rank_name == "Legendary"
        assert "/say" in perks
        assert "/entry" in str(perks)
    
    def test_checkpoint_voice_stats_no_active_users(self, voice_feature):
        """Test checkpointing with no users in voice."""
        voice_feature.voice_join_times = {}
        
        with patch.object(voice_feature, 'load_voice_stats', return_value={}):
            with patch.object(voice_feature, 'save_voice_stats') as mock_save:
                voice_feature.checkpoint_voice_stats(TEST_GUILD_ID)
                
                # Should not save if no active users
                mock_save.assert_not_called()
    
    def test_checkpoint_voice_stats_with_active_users(self, voice_feature):
        """Test checkpointing with users in voice channels."""
        import time
        now = time.time()
        
        voice_feature.voice_join_times = {
            "123456": now - 3600,  # User joined 1 hour ago
            "789012": now - 1800   # User joined 30 minutes ago
        }
        
        with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 7200}):
            with patch.object(voice_feature, 'save_voice_stats') as mock_save:
                with patch('time.time', return_value=now):
                    voice_feature.checkpoint_voice_stats(TEST_GUILD_ID)
                    
                    # Should save updated stats
                    mock_save.assert_called_once()
                    # guild_id is first param, data is second
                    saved_data = mock_save.call_args[0][1]
                    
                    # User 123456 should have 7200 + ~3600 seconds
                    assert saved_data["123456"] >= 10800
                    # User 789012 should have ~1800 seconds
                    assert saved_data["789012"] >= 1800
    
    @pytest.mark.asyncio
    async def test_say_cmd_insufficient_rank(self, voice_feature, mock_interaction):
        """Test /say command fails for users below Gold rank."""
        mock_interaction.user.id = 123456
        
        with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 0}):
            await voice_feature.say_cmd.callback(voice_feature, mock_interaction, "test message")
            
            # Should reject with rank error
            mock_interaction.followup.send.assert_called_once()
            call_args = mock_interaction.followup.send.call_args
            assert "Gold" in call_args[0][0]
            assert "Iron" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_say_cmd_not_in_voice(self, voice_feature, mock_interaction):
        """Test /say command fails if user not in voice channel."""
        mock_interaction.user.id = 123456
        mock_interaction.user.voice = None
        
        # Give user Gold rank (30+ hours)
        with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 108000}):
            await voice_feature.say_cmd.callback(voice_feature, mock_interaction, "test message")
            
            # Should reject because not in voice
            mock_interaction.followup.send.assert_called_once()
            assert "voice channel" in mock_interaction.followup.send.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_say_cmd_message_too_long(self, voice_feature, mock_interaction):
        """Test /say command fails for messages over 50 characters."""
        mock_interaction.user.id = 123456
        mock_interaction.user.voice = MagicMock()
        
        long_message = "a" * 51
        
        with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 108000}):
            await voice_feature.say_cmd.callback(voice_feature, mock_interaction, long_message)
            
            mock_interaction.followup.send.assert_called_once()
            assert "quá dài" in mock_interaction.followup.send.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_say_cmd_success(self, voice_feature, mock_interaction):
        """Test /say command succeeds for Gold+ user in voice with valid message."""
        mock_interaction.user.id = 123456
        mock_interaction.user.voice = MagicMock()
        
        with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 108000}):
            with patch('time.time', return_value=1000):
                await voice_feature.say_cmd.callback(voice_feature, mock_interaction, "test message")
                
                # Should add to queue successfully
                mock_interaction.followup.send.assert_called_once()
                assert "✅" in mock_interaction.followup.send.call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_rank_cmd_add_self(self, voice_feature, mock_interaction, mock_bot):
        """Test /rank add to add yourself to competition."""
        mock_interaction.user.id = 123456
        mock_interaction.guild.id = TEST_GUILD_ID
        
        mock_channel = AsyncMock()
        mock_channel.id = 999888
        mock_channel.mention = "<#999888>"
        
        mock_category = MagicMock()
        mock_category.create_voice_channel = AsyncMock(return_value=mock_channel)
        mock_bot.get_channel.return_value = mock_category
        
        with patch.object(voice_feature, 'load_competitors', return_value={}):
            with patch.object(voice_feature, 'save_competitors') as mock_save:
                with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 3600}):
                    with patch.object(voice_feature, 'save_voice_stats'):
                        await voice_feature.rank_cmd.callback(voice_feature, mock_interaction, action="add", user=None)
                        
                        # Should create channel and save competitor
                        mock_category.create_voice_channel.assert_called_once()
                        mock_save.assert_called_once()
                        
                        # guild_id is first param, data is second
                        saved_data = mock_save.call_args[0][1]
                        assert "123456" in saved_data
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_join(self, voice_feature, mock_member):
        """Test tracking when admin joins voice channel."""
        mock_member.guild_permissions.administrator = True
        mock_member.id = 123456
        mock_member.guild.id = TEST_GUILD_ID
        
        before = MagicMock()
        before.channel = None
        
        after = MagicMock()
        after.channel = MagicMock()
        after.channel.id = 999
        
        with patch('time.time', return_value=1000):
            with patch.object(voice_feature, 'load_voice_stats', return_value={}):
                await voice_feature.on_voice_state_update(mock_member, before, after)
                
                # Should track join time
                assert "123456" in voice_feature.voice_join_times
                assert voice_feature.voice_join_times["123456"] == 1000
    
    @pytest.mark.asyncio
    async def test_on_voice_state_update_leave(self, voice_feature, mock_member):
        """Test saving stats when admin leaves voice channel."""
        mock_member.guild_permissions.administrator = True
        mock_member.id = 123456
        mock_member.guild.id = TEST_GUILD_ID
        
        # User was in voice for 1 hour
        voice_feature.voice_join_times["123456"] = 1000
        
        before = MagicMock()
        before.channel = MagicMock()
        
        after = MagicMock()
        after.channel = None
        
        with patch('time.time', return_value=4600):  # 1 hour later
            with patch.object(voice_feature, 'load_voice_stats', return_value={"123456": 0}):
                with patch.object(voice_feature, 'save_voice_stats') as mock_save:
                    await voice_feature.on_voice_state_update(mock_member, before, after)
                    
                    # Should save ~1 hour (3600 seconds)
                    mock_save.assert_called_once()
                    # guild_id is first param, data is second
                    saved_data = mock_save.call_args[0][1]
                    assert saved_data["123456"] >= 3600
    
    @pytest.mark.asyncio
    async def test_rank_cmd_set_not_admin(self, voice_feature, mock_interaction):
        """Test /rank set fails if user is not admin."""
        mock_interaction.user.guild_permissions.administrator = False
        mock_interaction.guild.id = TEST_GUILD_ID
        
        mock_user = MagicMock()
        mock_user.id = 789012
        mock_user.display_name = "TestUser"
        
        await voice_feature.rank_cmd.callback(voice_feature, mock_interaction, action="set", user=mock_user, seconds=180000)
        
        # Should reject with admin error
        mock_interaction.followup.send.assert_called_once()
        assert "admin" in mock_interaction.followup.send.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_rank_cmd_set_no_user(self, voice_feature, mock_interaction):
        """Test /rank set fails if no user specified."""
        mock_interaction.user.guild_permissions.administrator = True
        mock_interaction.guild.id = TEST_GUILD_ID
        
        await voice_feature.rank_cmd.callback(voice_feature, mock_interaction, action="set", user=None, seconds=180000)
        
        # Should reject with user error
        mock_interaction.followup.send.assert_called_once()
        assert "must specify a user" in mock_interaction.followup.send.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_rank_cmd_set_negative_seconds(self, voice_feature, mock_interaction):
        """Test /rank set fails for negative seconds."""
        mock_interaction.user.guild_permissions.administrator = True
        mock_interaction.guild.id = TEST_GUILD_ID
        
        mock_user = MagicMock()
        mock_user.id = 789012
        mock_user.display_name = "TestUser"
        
        await voice_feature.rank_cmd.callback(voice_feature, mock_interaction, action="set", user=mock_user, seconds=-100)
        
        # Should reject with validation error
        mock_interaction.followup.send.assert_called_once()
        assert "valid number" in mock_interaction.followup.send.call_args[0][0].lower()
    
    @pytest.mark.asyncio
    async def test_rank_cmd_set_success(self, voice_feature, mock_interaction):
        """Test /rank set successfully updates user's voice hours."""
        mock_interaction.user.guild_permissions.administrator = True
        mock_interaction.guild.id = TEST_GUILD_ID
        
        mock_user = MagicMock()
        mock_user.id = 789012
        mock_user.display_name = "TestUser"
        
        # User currently has 36000 seconds (10 hours)
        with patch.object(voice_feature, 'load_voice_stats', return_value={"789012": 36000}):
            with patch.object(voice_feature, 'save_voice_stats') as mock_save:
                await voice_feature.rank_cmd.callback(voice_feature, mock_interaction, action="set", user=mock_user, seconds=180000)
                
                # Should save new hours
                mock_save.assert_called_once()
                saved_data = mock_save.call_args[0][1]
                assert saved_data["789012"] == 180000
                
                # Should confirm update
                mock_interaction.followup.send.assert_called_once()
                call_args = mock_interaction.followup.send.call_args[0][0]
                assert "✅" in call_args
                assert "180000" in call_args
                assert "Before" in call_args and "After" in call_args
