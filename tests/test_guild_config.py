"""
Unit tests for guild configuration and resource provisioning.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.guild_config import GuildConfigManager


@pytest.mark.unit
class TestGuildConfig:
    @pytest.mark.asyncio
    async def test_ensure_discord_resources_creates_defaults(self, tmp_path, monkeypatch):
        """Guild auto-provisioning should create channels, category, and rank roles."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BEANIE_BASE_DIR", str(tmp_path))

        manager = GuildConfigManager()

        guild = MagicMock()
        guild.id = 999001
        guild.channels = []
        guild.roles = []
        guild.get_channel = MagicMock(return_value=None)
        guild.create_text_channel = AsyncMock(
            side_effect=[
                MagicMock(id=111),
                MagicMock(id=222),
            ]
        )
        guild.create_category = AsyncMock(return_value=MagicMock(id=333))
        guild.create_role = AsyncMock(
            side_effect=[MagicMock(id=1000 + i) for i in range(9)]
        )

        await manager.ensure_discord_resources(guild)

        guild.create_text_channel.assert_any_call(
            manager.DEFAULT_BIRTHDAY_CHANNEL_NAME,
            reason="Auto-setup: birthday wishes channel",
        )
        guild.create_text_channel.assert_any_call(
            manager.DEFAULT_GENERAL_CHANNEL_NAME,
            reason="Auto-setup: monthly hall of fame channel",
        )
        guild.create_category.assert_called_once_with(
            manager.DEFAULT_RANK_CATEGORY_NAME,
            reason="Auto-setup: voice rank category",
        )
        assert guild.create_role.await_count == 9

        cfg = manager.get_guild_config(guild.id)
        assert cfg.get_birthday_channel_id() == 111
        assert cfg.get_general_channel_id() == 222
        assert cfg.get_rank_category_id() == 333
        assert len(cfg.get_rank_role_ids()) == 9
