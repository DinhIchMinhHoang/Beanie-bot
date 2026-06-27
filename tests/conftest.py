"""
Shared fixtures and mocks for testing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands

# Test guild ID constant used across all tests
TEST_GUILD_ID = 999888777666555


@pytest.fixture
def mock_bot():
    """Create a mock Discord bot."""
    bot = AsyncMock(spec=commands.Bot)
    bot.user = MagicMock()
    bot.user.id = 123456789
    bot.user.name = "BeanieBot"
    bot.guilds = []
    bot.voice_clients = []
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_user = AsyncMock(return_value=None)
    bot.add_cog = AsyncMock()
    bot.wait_until_ready = AsyncMock()
    return bot


@pytest.fixture
def mock_interaction():
    """Create a mock Discord interaction."""
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 987654321
    interaction.user.display_name = "TestUser"
    interaction.user.guild_permissions = MagicMock()
    interaction.user.guild_permissions.administrator = False
    interaction.user.voice = None
    interaction.guild = MagicMock()
    interaction.guild.id = TEST_GUILD_ID
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    
    # Mock client.fetch_user to return a user with display_name
    mock_user = MagicMock()
    mock_user.display_name = "User1"
    interaction.client = MagicMock()
    interaction.client.fetch_user = AsyncMock(return_value=mock_user)
    
    return interaction


@pytest.fixture
def mock_member():
    """Create a mock Discord member."""
    member = MagicMock(spec=discord.Member)
    member.id = 555666777
    member.display_name = "TestMember"
    member.guild_permissions = MagicMock()
    member.guild_permissions.administrator = False
    member.voice = None
    return member


@pytest.fixture
def mock_config():
    """Create a mock BotConfig with safe test values."""
    config = MagicMock()
    config.DISCORD_TOKEN = "test_discord_token"
    config.GEMINI_API_KEY = "test_gemini_key"
    config.OPENCODE_API_KEY = "test_opencode_key"
    config.OPENCODE_API_BASE = "https://opencode.ai/zen/go/v1"
    config.OPENCODE_MODEL = "deepseek-v4-flash-free"
    config.BIRTHDAY_FILE = "test_birthdays.json"
    config.VOICE_STATS_FILE = "test_voice_stats.json"
    config.COMPETITORS_FILE = "test_competitors.json"
    config.ENTRY_SETTINGS_FILE = "test_entry_settings.json"
    config.STATE_FILE = "test_state.json"
    config.BIRTHDAY_CHANNEL_ID = 123456
    config.GENERAL_CHANNEL_ID = 234567
    config.RANK_CATEGORY_ID = 345678
    config.RANK_ROLE_IDS = [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009]
    config.BIRTHDAY_WISHES = ["Happy birthday {name}!", "Chúc mừng sinh nhật {name}!"]
    config.MEMORY_LIMIT = 300
    config.WARNING_THRESHOLD = 294
    config.COOLDOWN_MINUTES = 60
    config.CHUNK_SIZE = 1900
    config.VIETNAM_TZ = None  # Will be set in tests if needed
    
    # Mock guild_manager for multi-guild support
    mock_guild_config = MagicMock()
    mock_guild_config.birthday_file = "test_birthdays.json"
    mock_guild_config.voice_stats_file = "test_voice_stats.json"
    mock_guild_config.competitors_file = "test_competitors.json"
    mock_guild_config.entry_settings_file = "test_entry_settings.json"
    mock_guild_config.state_file = "test_state.json"
    mock_guild_config.chat_history_file = "test_chat_history.txt"
    mock_guild_config.get_birthday_channel_id = MagicMock(return_value=123456)
    mock_guild_config.get_birthday_channel_ids = MagicMock(return_value=[123456])
    mock_guild_config.set_birthday_channel_ids = MagicMock()
    mock_guild_config.add_birthday_channel_id = MagicMock(return_value=True)
    mock_guild_config.remove_birthday_channel_id = MagicMock(return_value=True)
    mock_guild_config.get_general_channel_id = MagicMock(return_value=234567)
    mock_guild_config.get_rank_category_id = MagicMock(return_value=345678)
    mock_guild_config.get_rank_role_ids = MagicMock(return_value=[1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009])
    mock_guild_config.get_file_path = MagicMock(side_effect=lambda x: f"test_{x}")
    
    config.get_guild_config = MagicMock(return_value=mock_guild_config)
    config.get_storage = None
    config.ensure_guild_setup = MagicMock()
    
    return config


@pytest.fixture
def temp_json_files(tmp_path, monkeypatch):
    """Create temporary JSON files for testing and set working directory."""
    monkeypatch.chdir(tmp_path)
    
    # Create test JSON files
    (tmp_path / "test_birthdays.json").write_text("{}")
    (tmp_path / "test_voice_stats.json").write_text("{}")
    (tmp_path / "test_competitors.json").write_text("{}")
    (tmp_path / "test_entry_settings.json").write_text("{}")
    (tmp_path / "test_state.json").write_text("{}")
    
    return tmp_path


@pytest.fixture
def mock_openai_client():
    """Create a mock AsyncOpenAI client."""
    client = AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client


@pytest.fixture
def mock_azure_client():
    """Create a mock Azure compute client."""
    client = MagicMock()
    client.virtual_machines = MagicMock()
    client.virtual_machines.begin_start = MagicMock()
    client.virtual_machines.begin_deallocate = MagicMock()
    return client
