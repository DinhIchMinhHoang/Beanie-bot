"""
Shared fixtures and mocks for testing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands


class MockStorage:
    """In-memory storage for testing. Implements all storage methods used by features."""

    def __init__(self):
        self.data = {}

    def _guild_key(self, guild_id: int, table: str):
        return (guild_id, table)

    def _get(self, guild_id: int, table: str, default=None):
        return self.data.get(self._guild_key(guild_id, table), default)

    def _set(self, guild_id: int, table: str, value):
        self.data[self._guild_key(guild_id, table)] = value

    def ensure_guild_initialized(self, guild_id: int, guild_dir: str, default_config: dict):
        key = self._guild_key(guild_id, "guild_config")
        if key not in self.data:
            self.data[key] = dict(default_config)

    def load_guild_config(self, guild_id: int):
        return self._get(guild_id, "guild_config")

    def save_guild_config(self, guild_id: int, config: dict):
        self._set(guild_id, "guild_config", config)

    def load_voice_stats(self, guild_id: int):
        return dict(self._get(guild_id, "voice_stats", {}))

    def save_voice_stats(self, guild_id: int, data: dict):
        self._set(guild_id, "voice_stats", dict(data))

    def load_all_time_voice_stats(self, guild_id: int):
        result = dict(self._get(guild_id, "voice_stats", {}))
        archives = self._get(guild_id, "voice_stats_archives", {})
        for archive_key, archive_data in archives.items():
            for uid, secs in archive_data.items():
                result[uid] = result.get(uid, 0) + int(secs or 0)
        return result

    def archive_voice_stats(self, guild_id: int, year: int, month: int, stats: dict):
        archives = self._get(guild_id, "voice_stats_archives", {})
        archives[f"{year}-{month:02d}"] = dict(stats)
        self._set(guild_id, "voice_stats_archives", archives)

    def load_voice_stats_archive(self, guild_id: int, year: int, month: int):
        archives = self._get(guild_id, "voice_stats_archives", {})
        return dict(archives.get(f"{year}-{month:02d}", {}))

    def load_competitors(self, guild_id: int):
        return dict(self._get(guild_id, "competitors", {}))

    def save_competitors(self, guild_id: int, data: dict):
        self._set(guild_id, "competitors", dict(data))

    def load_entry_settings(self, guild_id: int):
        return dict(self._get(guild_id, "entry_settings", {}))

    def save_entry_settings(self, guild_id: int, data: dict):
        self._set(guild_id, "entry_settings", dict(data))

    def load_state(self, guild_id: int):
        return dict(self._get(guild_id, "state", {}))

    def save_state(self, guild_id: int, data: dict):
        self._set(guild_id, "state", dict(data))

    def load_birthdays(self, guild_id: int):
        return dict(self._get(guild_id, "birthdays", {}))

    def save_birthdays(self, guild_id: int, data: dict):
        self._set(guild_id, "birthdays", dict(data))

    def append_chat_history(self, guild_id: int, role: str, entry_json: str, memory_limit: int):
        history = list(self._get(guild_id, "chat_history", []))
        history.append(entry_json)
        if len(history) > memory_limit:
            history = history[-memory_limit:]
        self._set(guild_id, "chat_history", history)

    def load_chat_history(self, guild_id: int):
        return list(self._get(guild_id, "chat_history", []))

    def load_purchases(self, guild_id: int):
        return list(self._get(guild_id, "purchases", []))

    def save_purchase(self, guild_id: int, purchase_data: dict):
        purchases = list(self._get(guild_id, "purchases", []))
        purchases.append(dict(purchase_data))
        self._set(guild_id, "purchases", purchases)

    def get_purchase(self, guild_id: int, user_id: int, month: str, item_type: str):
        purchases = self._get(guild_id, "purchases", [])
        for p in purchases:
            if (p.get("user_id") == user_id and p.get("month") == month and p.get("purchase_type") == item_type):
                return p.get("purchase_value", 0.0)
        return 0.0

    def clear_guild_purchases(self, guild_id: int):
        self._set(guild_id, "purchases", [])

    def get_active_custom_events(self, guild_id: int, now_iso: str):
        return list(self._get(guild_id, "events", []))

    def clear_purchases(self, guild_id: int):
        self._set(guild_id, "purchases", [])

    def get_balance(self, guild_id: int, user_id: int) -> float:
        accounts = self._get(guild_id, "economy_accounts", {})
        return accounts.get(user_id, 0.0)

    def add_coins(self, guild_id: int, user_id: int, amount: float) -> float:
        accounts = dict(self._get(guild_id, "economy_accounts", {}))
        accounts[user_id] = accounts.get(user_id, 0.0) + amount
        self._set(guild_id, "economy_accounts", accounts)
        return accounts[user_id]

    def spend_coins(self, guild_id: int, user_id: int, amount: float) -> bool:
        balance = self.get_balance(guild_id, user_id)
        if balance < amount:
            return False
        self.add_coins(guild_id, user_id, -amount)
        return True

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
    config.OPENROUTER_API_KEY = "test_openrouter_key"
    config.OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
    config.OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"
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
    mock_guild_config.get_birthday_channel_id = MagicMock(return_value=123456)
    mock_guild_config.get_birthday_channel_ids = MagicMock(return_value=[123456])
    mock_guild_config.set_birthday_channel_ids = MagicMock()
    mock_guild_config.add_birthday_channel_id = MagicMock(return_value=True)
    mock_guild_config.remove_birthday_channel_id = MagicMock(return_value=True)
    mock_guild_config.get_general_channel_id = MagicMock(return_value=234567)
    mock_guild_config.get_rank_category_id = MagicMock(return_value=345678)
    mock_guild_config.get_rank_role_ids = MagicMock(return_value=[1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009])
    
    config.get_guild_config = MagicMock(return_value=mock_guild_config)
    config.get_storage = MagicMock(return_value=MockStorage())
    config.ensure_guild_setup = MagicMock()
    
    return config


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
