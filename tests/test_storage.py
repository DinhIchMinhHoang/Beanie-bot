"""Unit tests for SQLite storage migration and persistence."""

import json

import pytest

from core.guild_config import GuildConfig
from core.storage import get_storage


@pytest.mark.unit
class TestSQLiteStorage:
    @pytest.mark.skip(reason="Migration from JSON to SQLite is now disabled in core/storage.py - all data already migrated")
    def test_storage_migrates_existing_guild_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BEANIE_BASE_DIR", str(tmp_path))

        guild_id = 123456789
        guild_dir = tmp_path / "data" / "guilds" / str(guild_id)
        guild_dir.mkdir(parents=True)

        (guild_dir / "guild_config.json").write_text(
            json.dumps(
                {
                    "birthday_channel_id": 123,
                    "birthday_channel_ids": [123, 456],
                    "rank_category_id": 789,
                    "general_channel_id": 321,
                    "auto_shutdown_channel_id": None,
                    "rank_role_ids": [1, 2, 3],
                    "features": {"birthday": True, "voice_tracking": True, "ai_chat": True},
                }
            ),
            encoding="utf-8",
        )
        (guild_dir / "birthdays.json").write_text(json.dumps({"42": "25/12"}), encoding="utf-8")
        (guild_dir / "voice_stats.json").write_text(json.dumps({"42": {"total": 3600}}), encoding="utf-8")
        (guild_dir / "competitors.json").write_text(json.dumps({"42": 999}), encoding="utf-8")
        (guild_dir / "entry_settings.json").write_text(
            json.dumps({"42": {"enabled": True, "type": "default"}}),
            encoding="utf-8",
        )
        (guild_dir / "state.json").write_text(json.dumps({"last_reset_month": 3}), encoding="utf-8")
        (guild_dir / "chat_history.txt").write_text(
            "[2026-03-13T00:00:00+00:00] User: hello\n",
            encoding="utf-8",
        )
        (guild_dir / "archive_2026_03.json").write_text(json.dumps({"42": 7200}), encoding="utf-8")

        cfg = GuildConfig(guild_id)
        storage = get_storage(str(tmp_path))

        assert cfg.get_birthday_channel_ids() == [123, 456]
        assert storage.load_birthdays(guild_id) == {"42": "25/12"}
        assert storage.load_voice_stats(guild_id) == {"42": 3600.0}
        assert storage.load_competitors(guild_id) == {"42": 999}
        assert storage.load_entry_settings(guild_id)["42"]["enabled"] is True
        assert storage.load_state(guild_id)["last_reset_month"] == 3
        assert storage.load_chat_history(guild_id) == ["[2026-03-13T00:00:00+00:00] User: hello"]
        assert storage.load_all_time_voice_stats(guild_id) == {"42": 10800.0}

    @pytest.mark.skip(reason="Migration from JSON to SQLite is now disabled in core/storage.py - all data already migrated")
    def test_storage_migrates_legacy_root_files_for_primary_guild(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BEANIE_BASE_DIR", str(tmp_path))

        guild_id = 1052940754600874105
        monkeypatch.setenv("GUILD_ID", str(guild_id))

        guild_dir = tmp_path / "data" / "guilds" / str(guild_id)
        guild_dir.mkdir(parents=True)

        (tmp_path / "guild_config.json").write_text(
            json.dumps(
                {
                    "birthday_channel_id": 123,
                    "birthday_channel_ids": [123],
                    "rank_category_id": 789,
                    "general_channel_id": 321,
                    "auto_shutdown_channel_id": None,
                    "rank_role_ids": [1, 2, 3],
                    "features": {"birthday": True, "voice_tracking": True, "ai_chat": True},
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "voice_stats.json").write_text(json.dumps({"42": {"total": 3600}}), encoding="utf-8")
        (tmp_path / "competitors.json").write_text(json.dumps({"42": 999}), encoding="utf-8")
        (tmp_path / "state.json").write_text(json.dumps({"last_reset_month": 3}), encoding="utf-8")
        (tmp_path / "chat_history.txt").write_text(
            "[2026-03-13T00:00:00+00:00] User: hello\n",
            encoding="utf-8",
        )
        (tmp_path / "archive_2026_03.json").write_text(json.dumps({"42": 7200}), encoding="utf-8")

        cfg = GuildConfig(guild_id)
        storage = get_storage(str(tmp_path))

        assert cfg.get_birthday_channel_ids() == [123]
        assert cfg.get_general_channel_id() == 321
        assert cfg.get_rank_category_id() == 789
        assert storage.load_voice_stats(guild_id) == {"42": 3600.0}
        assert storage.load_competitors(guild_id) == {"42": 999}
        assert storage.load_state(guild_id)["last_reset_month"] == 3
        assert storage.load_chat_history(guild_id) == ["[2026-03-13T00:00:00+00:00] User: hello"]
        assert storage.load_all_time_voice_stats(guild_id) == {"42": 10800.0}

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