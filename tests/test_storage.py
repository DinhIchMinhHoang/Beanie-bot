"""Unit tests for SQLite storage migration and persistence."""

import pytest

from core.guild_config import GuildConfig
from core.storage import get_storage


@pytest.mark.unit
class TestSQLiteStorage:
    def test_chat_history_trim_uses_sqlite_limit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BEANIE_BASE_DIR", str(tmp_path))

        guild_id = 987654321
        GuildConfig(guild_id)
        storage = get_storage(str(tmp_path))

        storage.append_chat_history(guild_id, "u1", "one", 2)
        storage.append_chat_history(guild_id, "u2", "two", 2)
        storage.append_chat_history(guild_id, "u3", "three", 2)

        history = storage.load_chat_history(guild_id)
        assert len(history) == 2
        assert history[0].endswith("u2: two")
        assert history[1].endswith("u3: three")

    def test_load_voice_stats_archive_roundtrip(self, tmp_path, monkeypatch):
        """Test load_voice_stats_archive returns what was stored."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BEANIE_BASE_DIR", str(tmp_path))

        guild_id = 555666777
        GuildConfig(guild_id)
        storage = get_storage(str(tmp_path))

        storage.archive_voice_stats(guild_id, 2026, 3, {"42": 3600.0, "99": 7200.0})
        archived = storage.load_voice_stats_archive(guild_id, 2026, 3)

        assert archived == {"42": 3600.0, "99": 7200.0}

        # Non-existent archive returns empty dict
        missing = storage.load_voice_stats_archive(guild_id, 2025, 1)
        assert missing == {}