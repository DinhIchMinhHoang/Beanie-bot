"""
Configuration Module for Beanie Bot
Stores all configuration constants and environment variables
"""

import os
from dotenv import load_dotenv
import pytz
from core.guild_config import GuildConfigManager
from core.storage import get_storage, resolve_base_dir


# Load environment variables
load_dotenv()


class BotConfig:
    """Configuration class for Beanie Bot."""
    
    # Guild Configuration Manager (multi-guild support)
    guild_manager = GuildConfigManager()
    _storage = None
    
    # Timezone
    VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
    
    # Discord Configuration
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    GUILD_ID = int(os.getenv("GUILD_ID") or 0)
    
    # External API Keys
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_API_BASE = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash")
    
    # Memory/Chat Configuration
    MEMORY_LIMIT = 300
    WARNING_THRESHOLD = 294
    COOLDOWN_MINUTES = 60
    CHUNK_SIZE = 1900
    
    # Azure Configuration
    AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
    AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP")
    AZURE_VM_NAME = os.getenv("AZURE_VM_NAME")
    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    
    # SSH Configuration
    SSH_HOST = os.getenv("SSH_HOST")
    SSH_USER = os.getenv("SSH_USER")
    SSH_PASSWORD = os.getenv("SSH_PASSWORD")
    
    # Minecraft Configuration
    MC_SERVER_IP = os.getenv("MC_SERVER_IP")
    SHUTDOWN_MAX_WAIT = int(os.getenv("SHUTDOWN_MAX_WAIT", "300"))
    SHUTDOWN_POLL_INTERVAL = int(os.getenv("SHUTDOWN_POLL_INTERVAL", "3"))
    MANUAL_GRACE_MINUTES = int(os.getenv("MANUAL_GRACE_MINUTES", "10"))
    
    # RCON Configuration
    RCON_ENABLED = os.getenv("RCON_ENABLED", "false").lower() in ("1", "true", "yes")
    RCON_HOST = os.getenv("RCON_HOST") or MC_SERVER_IP
    RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
    RCON_PASSWORD = os.getenv("RCON_PASSWORD")
    
    # Auto-shutdown Configuration
    AUTO_SHUTDOWN_CHANNEL_ID = int(os.getenv("AUTO_SHUTDOWN_CHANNEL_ID") or 0)
    MAX_EMPTY_CHECKS = int(os.getenv("MAX_EMPTY_CHECKS", "3"))
    LAST_REQUEST_CHANNEL_FILE = "last_request_channel.txt"
    
    # Voice Tracking Data Files
    BIRTHDAY_FILE = "birthdays.json"
    VOICE_STATS_FILE = "voice_stats.json"
    COMPETITORS_FILE = "competitors.json"
    ENTRY_SETTINGS_FILE = "entry_settings.json"
    STATE_FILE = "state.json"
    
    # Discord Channel IDs
    BIRTHDAY_CHANNEL_ID = 1054049999475965972  # Voice chat text channel
    RANK_CATEGORY_ID = 1472493127934677185  # Category where rank channels will be created
    GENERAL_CHANNEL_ID = 1475806362393907282  # General channel for monthly reset announcements
    
    # Rank Role IDs
    RANK_ROLE_IDS = [
        1475819335514849391,  # Iron
        1475808729705353290,  # Bronze
        1475808847649181778,  # Silver
        1475808898370769018,  # Gold
        1475809119049875528,  # Platinum
        1475808953681051738,  # Diamond
        1475813832411709461,  # Elite
        1475813978201653330,  # Immortal
        1475814299120435301,  # Legendary
    ]
    
    # Birthday Wishes Messages
    BIRTHDAY_WISHES = [
        "🎉 Chúc mừng sinh nhật {name}! Tuổi mới vạn sự như ý, tiền vào như nước! 💰🎂",
        "🎂 Happy Birthday {name}! Chúc bạn luôn vui vẻ, hạnh phúc và... không bao giờ già! 😎🎈",
        "🥳 Sinh nhật vui vẻ {name}! Một tuổi mới thêm xinh đẹp, thêm giàu, thêm... béo? 😂🍰",
        "🎊 {name} ơi, sinh nhật zui zẻ nha! Chúc bạn luôn 'dope' và 'swag' như mọi khi! 🔥🎁",
        "🎉 Chúc mừng sinh nhật {name}! Tuổi mới học giỏi, chơi khỏe, ăn ngon, ngủ sâu! 🌟🎂",
        "🎈 Happy Birthday to you {name}! May your day be as awesome as your memes! 🎮🎉",
        "🎂 {name} thêm một tuổi mới! Chúc bạn 'level up' thành công trong cuộc sống real! 🚀✨",
        "🥳 Sinh nhật vui vẻ {name}! Chúc bạn luôn tươi trẻ, năng động và không bao giờ hết pin! 🔋😄",
        "🎊 {name} ơi! Chúc mừng sinh nhật! Năm nay phải giàu hơn năm ngoái nha! 💎🎁",
        "🎉 Happy Birthday {name}! Chúc tuổi mới nhiều niềm vui, ít drama, full happiness! 🌈🎂",
        "🎂 Sinh nhật zui zẻ {name}! Chúc bạn luôn 'on top' và không bao giờ 'flop'! 🎯🔥",
        "🥳 {name} thêm tuổi rồi nè! Chúc ngày càng xinh/đẹp, giàu có và hạnh phúc! 💖🎈"
    ]
    
    # --- Multi-Guild Support Methods ---
    
    @classmethod
    def get_guild_config(cls, guild_id: int):
        """Get GuildConfig instance for a specific guild."""
        return cls.guild_manager.get_guild_config(guild_id)

    @classmethod
    def get_storage(cls):
        """Get the shared SQLite storage backend."""
        if cls._storage is None:
            cls._storage = get_storage(resolve_base_dir())
        return cls._storage
    
    @classmethod
    def ensure_guild_setup(cls, guild_id: int):
        """Ensure guild directory and config exist."""
        cls.guild_manager.ensure_guild_setup(guild_id)

    @classmethod
    async def ensure_guild_resources(cls, guild):
        """Ensure Discord channels/categories/roles exist for a guild."""
        await cls.guild_manager.ensure_discord_resources(guild)
