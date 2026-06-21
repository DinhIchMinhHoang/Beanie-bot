"""
Guild Configuration Manager
Handles per-guild settings and data paths
"""

import os
import json
import logging
from typing import List

import discord
from core.storage import get_storage, resolve_base_dir


class GuildConfig:
    """Manages configuration for individual guilds."""
    
    # Base paths
    DATA_DIR = "data"
    GUILDS_DIR = os.path.join(DATA_DIR, "guilds")
    SFX_DIR = os.path.join(DATA_DIR, "sfx")  # Global SFX storage
    
    def __init__(self, guild_id: int):
        self.guild_id = str(guild_id)
        self.base_dir = resolve_base_dir()
        self.data_dir = os.path.join(self.base_dir, self.DATA_DIR)
        self.guilds_dir = os.path.join(self.data_dir, "guilds")
        self.sfx_dir = os.path.join(self.data_dir, "sfx")
        self.guild_dir = os.path.join(self.guilds_dir, self.guild_id)
        self._config = self._load_guild_config()
    
    def _ensure_guild_directory(self):
        """Create guild directory structure if it doesn't exist."""
        os.makedirs(self.guild_dir, exist_ok=True)
        os.makedirs(self.sfx_dir, exist_ok=True)
        logging.info(f"Ensured guild directory exists: {self.guild_dir}")
    
    def _load_guild_config(self):
        """Load guild-specific configuration."""
        self._ensure_guild_directory()
        storage = get_storage(self.base_dir)
        storage.ensure_guild_initialized(int(self.guild_id), self.guild_dir, self._default_config())
        stored_config = storage.load_guild_config(int(self.guild_id))
        if stored_config:
            return self._normalize_config(stored_config)

        config_file = os.path.join(self.guild_dir, "guild_config.json")
        
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    normalized = self._normalize_config(config)
                    if normalized != config:
                        self._save_guild_config(normalized)
                    return normalized
            except Exception as e:
                logging.error(f"Failed to load guild config for {self.guild_id}: {e}")
                return self._default_config()
        else:
            # Create default config
            config = self._default_config()
            self._save_guild_config(config)
            return config
    
    def _default_config(self):
        """Return default guild configuration."""
        return {
            "birthday_channel_id": None,
            "birthday_channel_ids": [],
            "rank_category_id": None,
            "general_channel_id": None,
            "patch_notes_channel_id": None,
            "auto_shutdown_channel_id": None,
            "rank_role_ids": [],
            "features": {
                "birthday": True,
                "voice_tracking": True,
                "ai_chat": True,
                "minecraft": False
            }
        }

    def _normalize_config(self, config: dict) -> dict:
        """Normalize config shape to keep backward compatibility."""
        normalized = dict(config or {})

        # Ensure new birthday_channel_ids key exists and is aligned with legacy key.
        birthday_ids = normalized.get("birthday_channel_ids")
        if not isinstance(birthday_ids, list):
            birthday_ids = []

        birthday_ids = [cid for cid in birthday_ids if isinstance(cid, int)]
        legacy_id = normalized.get("birthday_channel_id")
        if isinstance(legacy_id, int) and legacy_id not in birthday_ids:
            birthday_ids.insert(0, legacy_id)

        normalized["birthday_channel_ids"] = birthday_ids
        normalized["birthday_channel_id"] = birthday_ids[0] if birthday_ids else None

        if "features" not in normalized or not isinstance(normalized["features"], dict):
            normalized["features"] = self._default_config()["features"]

        return normalized
    
    def _save_guild_config(self, config):
        """Save guild configuration."""
        try:
            get_storage(self.base_dir).save_guild_config(int(self.guild_id), config)
            logging.info(f"Saved guild config for {self.guild_id}")
        except Exception as e:
            logging.error(f"Failed to save guild config for {self.guild_id}: {e}")
    
    # --- File Path Methods ---
    
    def get_file_path(self, filename: str) -> str:
        """Get path for a guild-specific file."""
        return os.path.join(self.guild_dir, filename)
    
    @property
    def birthday_file(self) -> str:
        return self.get_file_path("birthdays.json")
    
    @property
    def voice_stats_file(self) -> str:
        return self.get_file_path("voice_stats.json")
    
    @property
    def competitors_file(self) -> str:
        return self.get_file_path("competitors.json")
    
    @property
    def entry_settings_file(self) -> str:
        return self.get_file_path("entry_settings.json")
    
    @property
    def state_file(self) -> str:
        return self.get_file_path("state.json")
    
    @property
    def chat_history_file(self) -> str:
        return self.get_file_path("chat_history.txt")
    
    # --- Channel/Role ID Methods ---
    
    def get_birthday_channel_id(self) -> int:
        """Get primary birthday announcement channel ID (legacy-compatible)."""
        channel_ids = self.get_birthday_channel_ids()
        if channel_ids:
            return channel_ids[0]
        return self._config.get("birthday_channel_id")

    def get_birthday_channel_ids(self) -> List[int]:
        """Get all birthday announcement channel IDs."""
        channel_ids = self._config.get("birthday_channel_ids", [])
        if not isinstance(channel_ids, list):
            channel_ids = []

        channel_ids = [cid for cid in channel_ids if isinstance(cid, int)]

        # Include legacy single ID if present.
        legacy_id = self._config.get("birthday_channel_id")
        if isinstance(legacy_id, int) and legacy_id not in channel_ids:
            channel_ids.insert(0, legacy_id)

        return channel_ids
    
    def set_birthday_channel_id(self, channel_id: int):
        """Set primary birthday announcement channel ID (also updates list)."""
        self._config["birthday_channel_id"] = channel_id
        if isinstance(channel_id, int):
            self._config["birthday_channel_ids"] = [channel_id]
        else:
            self._config["birthday_channel_ids"] = []
        self._save_guild_config(self._config)

    def set_birthday_channel_ids(self, channel_ids: List[int]):
        """Replace birthday announcement channel IDs."""
        ids = [cid for cid in channel_ids if isinstance(cid, int)]
        self._config["birthday_channel_ids"] = ids
        self._config["birthday_channel_id"] = ids[0] if ids else None
        self._save_guild_config(self._config)

    def add_birthday_channel_id(self, channel_id: int) -> bool:
        """Add birthday channel ID. Returns True if newly added."""
        if not isinstance(channel_id, int):
            return False

        channel_ids = self.get_birthday_channel_ids()
        if channel_id in channel_ids:
            return False

        channel_ids.append(channel_id)
        self.set_birthday_channel_ids(channel_ids)
        return True

    def remove_birthday_channel_id(self, channel_id: int) -> bool:
        """Remove birthday channel ID. Returns True if removed."""
        channel_ids = self.get_birthday_channel_ids()
        if channel_id not in channel_ids:
            return False

        channel_ids = [cid for cid in channel_ids if cid != channel_id]
        self.set_birthday_channel_ids(channel_ids)
        return True

    def cleanup_missing_birthday_channels(self, existing_channel_ids: List[int]):
        """Drop birthday channels that no longer exist in the guild."""
        existing = set(existing_channel_ids)
        channel_ids = self.get_birthday_channel_ids()
        cleaned = [cid for cid in channel_ids if cid in existing]
        if cleaned != channel_ids:
            self.set_birthday_channel_ids(cleaned)
    
    def get_rank_category_id(self) -> int:
        """Get rank category ID."""
        return self._config.get("rank_category_id")
    
    def set_rank_category_id(self, category_id: int):
        """Set rank category ID."""
        self._config["rank_category_id"] = category_id
        self._save_guild_config(self._config)
    
    def get_general_channel_id(self) -> int:
        """Get general channel ID."""
        return self._config.get("general_channel_id")
    
    def set_general_channel_id(self, channel_id: int):
        """Set general channel ID."""
        self._config["general_channel_id"] = channel_id
        self._save_guild_config(self._config)
    
    def get_patch_notes_channel_id(self) -> int:
        """Get patch notes channel ID."""
        return self._config.get("patch_notes_channel_id")
    
    def set_patch_notes_channel_id(self, channel_id: int):
        """Set patch notes channel ID."""
        self._config["patch_notes_channel_id"] = channel_id
        self._save_guild_config(self._config)
    
    def get_rank_role_ids(self) -> list:
        """Get list of rank role IDs."""
        return self._config.get("rank_role_ids", [])
    
    def set_rank_role_ids(self, role_ids: list):
        """Set rank role IDs."""
        self._config["rank_role_ids"] = role_ids
        self._save_guild_config(self._config)
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled for this guild."""
        return self._config.get("features", {}).get(feature_name, True)
    
    # --- Global SFX Methods ---
    
    @classmethod
    def get_user_sfx_path(cls, user_id: int) -> str:
        """Get path for user's custom entrance sound (global)."""
        return os.path.join(resolve_base_dir(), cls.SFX_DIR, f"{user_id}.mp3")
    
    @classmethod
    def get_temp_tts_path(cls, user_id: int) -> str:
        """Get path for temporary TTS file (global)."""
        import time
        timestamp = int(time.time() * 1000)
        return os.path.join(resolve_base_dir(), cls.SFX_DIR, f"temp_{user_id}_{timestamp}.mp3")


class GuildConfigManager:
    """Manages GuildConfig instances for all guilds."""
    
    def __init__(self):
        self._configs = {}

    DEFAULT_BIRTHDAY_CHANNEL_NAME = "birthday-wishes"
    DEFAULT_RANK_CATEGORY_NAME = "⎯ 📊 Voice Chat Ranking ⎯"
    DEFAULT_GENERAL_CHANNEL_NAME = "🏆・hall_of_fame"
    DEFAULT_PATCH_NOTES_CHANNEL_NAME = "🫛・beanie_patch_update"
    DEFAULT_RANK_ROLES = [
        ("🦴・Iron", 0x95A5A6),
        ("⚒️・Bronze", 0xC27C0E),
        ("⚔️・Silver", 0xE2E2E2),
        ("🔱・Gold", 0xD4AC0B),
        ("💠・Platinum", 0x0099FF),
        ("🔮・Diamond", 0xFB00FF),
        ("🍀・Elite", 0x2ECC71),
        ("☄️・Immortal", 0xFF0004),
        ("👑・Legendary", 0xFFCC00),
    ]
    
    def get_guild_config(self, guild_id: int) -> GuildConfig:
        """Get or create GuildConfig for a guild."""
        if guild_id not in self._configs:
            self._configs[guild_id] = GuildConfig(guild_id)
        return self._configs[guild_id]
    
    def ensure_guild_setup(self, guild_id: int):
        """Ensure guild directory and config exist."""
        config = self.get_guild_config(guild_id)
        config._ensure_guild_directory()
        logging.info(f"Guild {guild_id} setup complete")

    async def ensure_discord_resources(self, guild: discord.Guild):
        """Ensure required channels/categories/roles exist for a guild."""
        guild_config = self.get_guild_config(guild.id)

        # Keep birthday channel list clean from deleted channels.
        guild_config.cleanup_missing_birthday_channels([ch.id for ch in guild.channels])

        # 1) Birthday text channel (primary channel in list)
        birthday_channel_ids = guild_config.get_birthday_channel_ids()
        birthday_channel = None
        for channel_id in birthday_channel_ids:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                birthday_channel = channel
                break

        if birthday_channel is None:
            try:
                birthday_channel = await guild.create_text_channel(
                    self.DEFAULT_BIRTHDAY_CHANNEL_NAME,
                    reason="Auto-setup: birthday wishes channel",
                )
                guild_config.set_birthday_channel_ids([birthday_channel.id])
                logging.info(f"Created birthday channel for guild {guild.id}: {birthday_channel.id}")
            except Exception as e:
                logging.warning(f"Failed to create birthday channel for guild {guild.id}: {e}")

        # 2) Rank category
        rank_category = None
        rank_category_id = guild_config.get_rank_category_id()
        if rank_category_id:
            channel = guild.get_channel(rank_category_id)
            if isinstance(channel, discord.CategoryChannel):
                rank_category = channel

        if rank_category is None:
            try:
                rank_category = await guild.create_category(
                    self.DEFAULT_RANK_CATEGORY_NAME,
                    reason="Auto-setup: voice rank category",
                )
                guild_config.set_rank_category_id(rank_category.id)
                logging.info(f"Created rank category for guild {guild.id}: {rank_category.id}")
            except Exception as e:
                logging.warning(f"Failed to create rank category for guild {guild.id}: {e}")

        # 3) Hall of fame channel
        general_channel = None
        general_channel_id = guild_config.get_general_channel_id()
        if general_channel_id:
            channel = guild.get_channel(general_channel_id)
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                general_channel = channel

        if general_channel is None:
            try:
                general_channel = await guild.create_text_channel(
                    self.DEFAULT_GENERAL_CHANNEL_NAME,
                    reason="Auto-setup: monthly hall of fame channel",
                )
                guild_config.set_general_channel_id(general_channel.id)
                logging.info(f"Created hall of fame channel for guild {guild.id}: {general_channel.id}")
            except Exception as e:
                logging.warning(f"Failed to create hall of fame channel for guild {guild.id}: {e}")

        # 4) Rank roles in the expected order
        configured_role_ids = guild_config.get_rank_role_ids()
        valid_configured_roles = [rid for rid in configured_role_ids if guild.get_role(rid)]

        if len(valid_configured_roles) != len(self.DEFAULT_RANK_ROLES):
            role_ids = []
            for role_name, color_value in self.DEFAULT_RANK_ROLES:
                existing_role = discord.utils.get(guild.roles, name=role_name)
                if existing_role:
                    role_ids.append(existing_role.id)
                    continue

                try:
                    role = await guild.create_role(
                        name=role_name,
                        colour=discord.Colour(color_value),
                        reason="Auto-setup: voice rank roles",
                        mentionable=False,
                        hoist=False,
                    )
                    role_ids.append(role.id)
                except Exception as e:
                    logging.warning(f"Failed to create role '{role_name}' for guild {guild.id}: {e}")

            if role_ids:
                guild_config.set_rank_role_ids(role_ids)

        # 5) Patch notes channel
        patch_notes_channel = None
        patch_notes_channel_id = guild_config.get_patch_notes_channel_id()
        if patch_notes_channel_id:
            channel = guild.get_channel(patch_notes_channel_id)
            if isinstance(channel, discord.TextChannel):
                patch_notes_channel = channel

        if patch_notes_channel is None:
            try:
                patch_notes_channel = await guild.create_text_channel(
                    self.DEFAULT_PATCH_NOTES_CHANNEL_NAME,
                    reason="Auto-setup: patch update notification channel",
                )
                guild_config.set_patch_notes_channel_id(patch_notes_channel.id)
                logging.info(f"Created patch notes channel for guild {guild.id}: {patch_notes_channel.id}")
            except Exception as e:
                logging.warning(f"Failed to create patch notes channel for guild {guild.id}: {e}")
