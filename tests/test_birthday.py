"""
Unit tests for Birthday feature module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from datetime import datetime
import json
import pytz

from features.birthday import BirthdayFeature
from tests.conftest import TEST_GUILD_ID


@pytest.mark.unit
class TestBirthdayFeature:
    """Test suite for BirthdayFeature cog."""
    
    @pytest.fixture
    def birthday_feature(self, mock_bot, mock_config):
        """Create BirthdayFeature instance with mocked dependencies."""
        with patch.object(BirthdayFeature, 'birthday_check'):
            feature = BirthdayFeature(mock_bot, mock_config)
            feature.birthday_check.start = MagicMock()  # Don't start the task loop
        return feature
    
    def test_initialization(self, birthday_feature, mock_bot, mock_config):
        """Test that BirthdayFeature initializes correctly."""
        assert birthday_feature.bot == mock_bot
        assert birthday_feature.config == mock_config
        assert birthday_feature.last_birthday_check is None
    
    def test_load_birthdays_empty(self, birthday_feature):
        """Test loading birthdays when file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            result = birthday_feature.load_birthdays(TEST_GUILD_ID)
            assert result == {}
    
    def test_load_birthdays_with_data(self, birthday_feature):
        """Test loading birthdays from existing file."""
        test_data = {"123456": "25/12", "789012": "01/01"}
        
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(test_data))):
                result = birthday_feature.load_birthdays(TEST_GUILD_ID)
                assert result == test_data
    
    def test_save_birthdays(self, birthday_feature, mock_config):
        """Test saving birthdays to file."""
        test_data = {"123456": "25/12"}
        
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)
        m = mock_open()
        with patch('builtins.open', m):
            birthday_feature.save_birthdays(TEST_GUILD_ID, test_data)
            
        # Verify file was opened in write mode
        m.assert_called_once_with(guild_config.birthday_file, 'w', encoding='utf-8')
    
    @pytest.mark.asyncio
    async def test_birthday_cmd_add_not_admin(self, birthday_feature, mock_interaction):
        """Test /birthday add command fails for non-admin."""
        mock_interaction.user.guild_permissions.administrator = False
        
        await birthday_feature.birthday_cmd.callback(
            birthday_feature,
            mock_interaction, 
            action="add",
            user=None,
            date="25/12"
        )
        
        # Should send error message
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "❌" in call_args[0][0]
        assert call_args[1]['ephemeral'] is True
    
    @pytest.mark.asyncio
    async def test_birthday_cmd_add_success(self, birthday_feature, mock_interaction, mock_member):
        """Test /birthday add command succeeds for admin."""
        mock_interaction.user.guild_permissions.administrator = True
        
        with patch.object(birthday_feature, 'load_birthdays', return_value={}):
            with patch.object(birthday_feature, 'save_birthdays') as mock_save:
                await birthday_feature.birthday_cmd.callback(
                    birthday_feature,
                    mock_interaction,
                    action="add",
                    user=mock_member,
                    date="25/12"
                )
                
                # Verify guild_id and user ID
                mock_save.assert_called_once()
                # First argument should be guild_id
                assert mock_save.call_args[0][0] == TEST_GUILD_ID
                # Second argument is the data dict
                saved_data = mock_save.call_args[0][1]
                assert str(mock_member.id) in saved_data
                assert saved_data[str(mock_member.id)] == "25/12"
                
                # Should send success message
                mock_interaction.response.send_message.assert_called_once()
                call_args = mock_interaction.response.send_message.call_args
                assert "✅" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_birthday_cmd_list_empty(self, birthday_feature, mock_interaction):
        """Test /birthday list with no birthdays."""
        mock_interaction.user.guild_permissions.administrator = True
        
        with patch.object(birthday_feature, 'load_birthdays', return_value={}):
            await birthday_feature.birthday_cmd.callback(
                birthday_feature,
                mock_interaction,
                action="list",
                user=None,
                date=None
            )
            
            mock_interaction.response.send_message.assert_called_once()
            call_args = mock_interaction.response.send_message.call_args
            assert "No birthdays" in call_args[0][0]
    
    @pytest.mark.asyncio
    async def test_birthday_cmd_list_with_data(self, birthday_feature, mock_interaction, mock_bot):
        """Test /birthday list with existing birthdays."""
        mock_interaction.user.guild_permissions.administrator = True
        test_birthdays = {"123456": "25/12", "789012": "01/01"}
        
        # Mock fetch_user to return member objects
        mock_user1 = MagicMock()
        mock_user1.display_name = "User1"
        mock_user2 = MagicMock()
        mock_user2.display_name = "User2"
        
        birthday_feature.bot.fetch_user = AsyncMock(side_effect=[mock_user1, mock_user2])
        
        with patch.object(birthday_feature, 'load_birthdays', return_value=test_birthdays):
            await birthday_feature.birthday_cmd.callback(
                birthday_feature,
                mock_interaction,
                action="list",
                user=None,
                date=None
            )
            
            mock_interaction.response.send_message.assert_called_once()
            call_args = mock_interaction.response.send_message.call_args
            message = call_args[0][0]
            assert "User1" in message
            assert "25/12" in message
    
    @pytest.mark.asyncio
    async def test_birthday_check_not_midnight(self, birthday_feature, mock_config):
        """Test birthday check skips if not midnight."""
        # Mock timezone
        mock_config.VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
        
        # Mock current time to NOT be midnight (10:30 AM)
        mock_now = datetime(2026, 3, 12, 10, 30, 0, tzinfo=mock_config.VIETNAM_TZ)
        
        with patch('features.birthday.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            with patch.object(birthday_feature, 'load_birthdays') as mock_load:
                await birthday_feature.birthday_check()
                
                # Should NOT load birthdays since it's not hour 0
                mock_load.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_birthday_check_already_checked_today(self, birthday_feature, mock_config):
        """Test birthday check skips if already checked today (NEW FIX)."""
        mock_config.VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
        
        # Set check to today
        today = datetime(2026, 3, 12, 6, 0, 0, tzinfo=mock_config.VIETNAM_TZ).date()
        birthday_feature.last_birthday_check = today
        
        # Mock time to be midnight (hour 0)
        mock_now = datetime(2026, 3, 12, 0, 30, 0, tzinfo=mock_config.VIETNAM_TZ)
        
        with patch('features.birthday.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            with patch.object(birthday_feature, 'load_birthdays') as mock_load:
                await birthday_feature.birthday_check()
                
                # Should skip because already checked today
                mock_load.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_birthday_check_flexible_minute_window(self, birthday_feature, mock_config, mock_bot):
        """Test birthday check runs during HOUR 0 with any minute (NEW FIX)."""
        mock_config.VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
        
        # Set check to different day
        birthday_feature.last_birthday_check = datetime(2026, 3, 11, 6, 0, 0, tzinfo=mock_config.VIETNAM_TZ).date()
        
        # Test at 00:22 (which SHOULD work now after fix - it's hour 0)
        mock_now = datetime(2026, 3, 12, 0, 22, 0, tzinfo=mock_config.VIETNAM_TZ)
        today_str = "12/03"
        
        # Setup guild and birthday
        mock_guild = MagicMock()
        mock_guild.id = TEST_GUILD_ID
        birthday_feature.bot.guilds = [mock_guild]
        
        mock_channel = AsyncMock()
        birthday_feature.bot.get_channel.return_value = mock_channel
        
        mock_user = MagicMock()
        mock_user.display_name = "User"
        birthday_feature.bot.fetch_user = AsyncMock(return_value=mock_user)
        
        test_birthdays = {"123456": today_str}
        
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)
        guild_config.get_birthday_channel_ids.return_value = [123456]
        
        with patch('features.birthday.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            with patch.object(birthday_feature, 'load_birthdays', return_value=test_birthdays):
                await birthday_feature.birthday_check()
                
                # AFTER FIX: Should send birthday message (not skip due to minute != 0)
                mock_channel.send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_birthday_check_at_midnight_with_birthday(self, birthday_feature, mock_config, mock_bot):
        """Test birthday check sends message at midnight when there's a birthday."""
        # Mock timezone
        mock_config.VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
        
        # Mock current time to be midnight on March 12
        mock_now = datetime(2026, 3, 12, 0, 0, 0, tzinfo=mock_config.VIETNAM_TZ)
        
        # Setup birthday for today
        test_birthdays = {"123456": "12/03"}
        
        # Mock guild
        mock_guild = MagicMock()
        mock_guild.id = TEST_GUILD_ID
        birthday_feature.bot.guilds = [mock_guild]
        
        # Mock channel
        mock_channel = AsyncMock()
        birthday_feature.bot.get_channel.return_value = mock_channel
        
        # Mock user
        mock_user = MagicMock()
        mock_user.display_name = "BirthdayUser"
        birthday_feature.bot.fetch_user = AsyncMock(return_value=mock_user)
        
        # Mock birthday channel list to return one channel ID
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)
        guild_config.get_birthday_channel_ids.return_value = [123456]
        
        with patch('features.birthday.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            
            with patch.object(birthday_feature, 'load_birthdays', return_value=test_birthdays):
                birthday_feature.last_birthday_check = None  # Reset check
                await birthday_feature.birthday_check()
                
                # Should send birthday message
                mock_channel.send.assert_called_once()
                message = mock_channel.send.call_args[0][0]
                assert "BirthdayUser" in message

    @pytest.mark.asyncio
    async def test_birthday_channel_cmd_add_success(self, birthday_feature, mock_interaction, mock_config):
        """Test /birthday_channel add command adds a channel."""
        mock_interaction.user.guild_permissions.administrator = True
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)

        mock_channel = MagicMock()
        mock_channel.id = 555444333
        mock_channel.mention = "<#555444333>"

        guild_config.add_birthday_channel_id.return_value = True

        await birthday_feature.birthday_channel_cmd.callback(
            birthday_feature,
            mock_interaction,
            action="add",
            channel=mock_channel,
        )

        guild_config.add_birthday_channel_id.assert_called_once_with(555444333)
        mock_interaction.response.send_message.assert_called_once()
        sent_text = mock_interaction.response.send_message.call_args[0][0]
        assert "✅" in sent_text

    @pytest.mark.asyncio
    async def test_birthday_channel_cmd_list(self, birthday_feature, mock_interaction, mock_config):
        """Test /birthday_channel list command shows configured channels."""
        mock_interaction.user.guild_permissions.administrator = True
        guild_config = mock_config.get_guild_config(TEST_GUILD_ID)
        guild_config.get_birthday_channel_ids.return_value = [111, 222]

        await birthday_feature.birthday_channel_cmd.callback(
            birthday_feature,
            mock_interaction,
            action="list",
            channel=None,
        )

        mock_interaction.response.send_message.assert_called_once()
        sent_text = mock_interaction.response.send_message.call_args[0][0]
        assert "<#111>" in sent_text
        assert "<#222>" in sent_text

    @pytest.mark.asyncio
    async def test_birthday_channel_cmd_non_admin(self, birthday_feature, mock_interaction):
        """Test /birthday_channel command is admin only."""
        mock_interaction.user.guild_permissions.administrator = False

        await birthday_feature.birthday_channel_cmd.callback(
            birthday_feature,
            mock_interaction,
            action="list",
            channel=None,
        )

        mock_interaction.response.send_message.assert_called_once()
        sent_text = mock_interaction.response.send_message.call_args[0][0]
        assert "❌" in sent_text
