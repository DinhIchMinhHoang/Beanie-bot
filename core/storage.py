"""SQLite-backed persistence for Beanie Bot."""

import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import aiosqlite


ARCHIVE_FILE_RE = re.compile(r"^archive_(\d{4})_(\d{2})\.json$")
CHAT_HISTORY_RE = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s(?P<speaker>[^:]+):\s(?P<content>.*)$")

_STORAGES = {}
_STORAGES_LOCK = threading.Lock()


def resolve_base_dir(base_dir: str | None = None) -> str:
    """Resolve the workspace base directory for bot data."""
    candidate = base_dir or os.getenv("BEANIE_BASE_DIR") or os.getcwd()
    return os.path.abspath(candidate)


def get_storage(base_dir: str | None = None):
    """Get a storage instance scoped to the resolved base directory."""
    resolved = resolve_base_dir(base_dir)
    with _STORAGES_LOCK:
        storage = _STORAGES.get(resolved)
        if storage is None:
            storage = SQLiteStorage(resolved)
            _STORAGES[resolved] = storage
        return storage


class SQLiteStorage:
    """Thread-backed SQLite storage using aiosqlite for serialized access."""

    def __init__(self, base_dir: str):
        self.base_dir = resolve_base_dir(base_dir)
        self.data_dir = os.path.join(self.base_dir, "data")
        self.db_path = os.path.join(self.data_dir, "beanie.sqlite3")
        os.makedirs(self.data_dir, exist_ok=True)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="beanie-sqlite", daemon=True)
        self._started = threading.Event()
        self._thread.start()
        self._started.wait()
        self._call(self._initialize())

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def _call(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    async def _initialize(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA temp_store=MEMORY")
        await self._conn.execute("PRAGMA cache_size=-8192")
        await self._conn.execute("PRAGMA wal_autocheckpoint=100")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._create_schema()
        await self._run_migrations()
        await self._conn.commit()
        logging.info("SQLite storage ready at %s", self.db_path)

    async def _create_schema(self):
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                birthday_channel_id INTEGER,
                rank_category_id INTEGER,
                general_channel_id INTEGER,
                auto_shutdown_channel_id INTEGER,
                rank_role_ids_json TEXT NOT NULL,
                features_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guild_birthday_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS birthdays (
                guild_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                birthday TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                total_seconds REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS competitors (
                guild_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                channel_id INTEGER,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS entry_settings (
                guild_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS guild_state (
                guild_id INTEGER NOT NULL,
                state_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, state_key)
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                speaker TEXT NOT NULL,
                content TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS voice_stats_archive (
                guild_id INTEGER NOT NULL,
                archive_year INTEGER NOT NULL,
                archive_month INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                total_seconds REAL NOT NULL,
                PRIMARY KEY (guild_id, archive_year, archive_month, user_id)
            );

            CREATE TABLE IF NOT EXISTS tracked_voice_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                enabled BOOLEAN DEFAULT 1,
                created_at INTEGER,
                PRIMARY KEY (guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS channel_voice_stats (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                total_user_seconds REAL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, period)
            );

            CREATE TABLE IF NOT EXISTS channel_voice_stats_archive (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                archive_year INTEGER NOT NULL,
                archive_month INTEGER NOT NULL,
                total_user_seconds REAL,
                PRIMARY KEY (guild_id, channel_id, archive_year, archive_month)
            );

            CREATE TABLE IF NOT EXISTS economy_accounts (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                coins REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS economy_purchases (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                purchase_type TEXT NOT NULL,
                purchase_value REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, month, purchase_type)
            );

            CREATE TABLE IF NOT EXISTS economy_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'all',
                value REAL NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                reason TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            );

            -- Performance Indexes
            CREATE INDEX IF NOT EXISTS idx_voice_stats_guild_user 
                ON voice_stats(guild_id, user_id);
            
            CREATE INDEX IF NOT EXISTS idx_voice_stats_user 
                ON voice_stats(user_id);
            
            CREATE INDEX IF NOT EXISTS idx_birthdays_guild_user 
                ON birthdays(guild_id, user_id);
            
            CREATE INDEX IF NOT EXISTS idx_birthdays_date 
                ON birthdays(birthday);
            
            CREATE INDEX IF NOT EXISTS idx_chat_history_guild_timestamp 
                ON chat_history(guild_id, created_at DESC);
            
            CREATE INDEX IF NOT EXISTS idx_chat_history_speaker 
                ON chat_history(speaker);
            
            CREATE INDEX IF NOT EXISTS idx_competitors_guild_user 
                ON competitors(guild_id, user_id);
            
            CREATE INDEX IF NOT EXISTS idx_voice_stats_archive_guild 
                ON voice_stats_archive(guild_id, archive_year, archive_month);
            
            CREATE INDEX IF NOT EXISTS idx_channel_voice_stats_guild 
                ON channel_voice_stats(guild_id, channel_id);
            
            CREATE INDEX IF NOT EXISTS idx_guild_state_guild 
                ON guild_state(guild_id, state_key);
            """
        )

    def ensure_guild_initialized(self, guild_id: int, guild_dir: str, default_config: dict):
        self._call(self._ensure_guild_initialized(guild_id, guild_dir, default_config))

    async def _ensure_guild_initialized(self, guild_id: int, guild_dir: str, default_config: dict):
        os.makedirs(guild_dir, exist_ok=True)

        config_row = await self._fetchone(
            "SELECT guild_id FROM guild_config WHERE guild_id = ?",
            (guild_id,),
        )
        if config_row is None:
            config_file = self._get_migration_file_path(guild_id, guild_dir, "guild_config.json")
            config_data = self._read_json_file(config_file, default_config)
            await self._save_guild_config(guild_id, config_data)

        # Migration from JSON to SQLite has completed; keeping methods for reference/rollback.
        # The following migration calls are disabled since all data has been transferred.
        # Uncomment below if needed to re-enable migration from legacy JSON files.
        """
        await self._migrate_simple_json_table(
            guild_id,
            guild_dir,
            "birthdays.json",
            "birthdays",
            lambda data: [(guild_id, str(user_id), value) for user_id, value in (data or {}).items()],
            "INSERT OR REPLACE INTO birthdays (guild_id, user_id, birthday) VALUES (?, ?, ?)",
        )

        await self._migrate_simple_json_table(
            guild_id,
            guild_dir,
            "voice_stats.json",
            "voice_stats",
            lambda data: [
                (guild_id, str(user_id), self._normalize_voice_total(value))
                for user_id, value in (data or {}).items()
            ],
            "INSERT OR REPLACE INTO voice_stats (guild_id, user_id, total_seconds) VALUES (?, ?, ?)",
        )

        await self._migrate_simple_json_table(
            guild_id,
            guild_dir,
            "competitors.json",
            "competitors",
            lambda data: self._normalize_competitors(guild_id, data),
            "INSERT OR REPLACE INTO competitors (guild_id, user_id, channel_id) VALUES (?, ?, ?)",
        )

        await self._migrate_simple_json_table(
            guild_id,
            guild_dir,
            "entry_settings.json",
            "entry_settings",
            lambda data: [
                (guild_id, str(user_id), json.dumps(value, ensure_ascii=False))
                for user_id, value in (data or {}).items()
            ],
            "INSERT OR REPLACE INTO entry_settings (guild_id, user_id, settings_json) VALUES (?, ?, ?)",
        )

        await self._migrate_simple_json_table(
            guild_id,
            guild_dir,
            "state.json",
            "guild_state",
            lambda data: [
                (guild_id, str(key), json.dumps(value, ensure_ascii=False))
                for key, value in (data or {}).items()
            ],
            "INSERT OR REPLACE INTO guild_state (guild_id, state_key, value_json) VALUES (?, ?, ?)",
        )

        await self._migrate_chat_history(guild_id, guild_dir)
        await self._migrate_archives(guild_id, guild_dir)
        """
        await self._conn.commit()

    async def _migrate_simple_json_table(
        self,
        guild_id: int,
        guild_dir: str,
        filename: str,
        table_name: str,
        row_builder,
        insert_sql: str,
    ):
        count_row = await self._fetchone(
            f"SELECT COUNT(*) AS count FROM {table_name} WHERE guild_id = ?",
            (guild_id,),
        )
        if count_row and count_row["count"]:
            return

        file_path = self._get_migration_file_path(guild_id, guild_dir, filename)
        if not os.path.exists(file_path):
            return

        data = self._read_json_file(file_path, {})
        rows = row_builder(data)
        if not rows:
            legacy_file_path = self._get_legacy_root_file_path(guild_id, filename)
            if legacy_file_path and legacy_file_path != file_path:
                data = self._read_json_file(legacy_file_path, {})
                rows = row_builder(data)
        if rows:
            await self._conn.executemany(insert_sql, rows)

    async def _migrate_chat_history(self, guild_id: int, guild_dir: str):
        count_row = await self._fetchone(
            "SELECT COUNT(*) AS count FROM chat_history WHERE guild_id = ?",
            (guild_id,),
        )
        if count_row and count_row["count"]:
            return

        history_file = self._get_migration_file_path(guild_id, guild_dir, "chat_history.txt")
        if not os.path.exists(history_file):
            return

        rows = []
        with open(history_file, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.rstrip("\n")
                if not text:
                    continue
                match = CHAT_HISTORY_RE.match(text)
                if match:
                    created_at = match.group("timestamp")
                    speaker = match.group("speaker")
                    content = match.group("content")
                else:
                    created_at = datetime.now(timezone.utc).isoformat()
                    speaker = "unknown"
                    content = text
                rows.append((guild_id, created_at, speaker, content))

        if rows:
            await self._conn.executemany(
                "INSERT INTO chat_history (guild_id, created_at, speaker, content) VALUES (?, ?, ?, ?)",
                rows,
            )

    async def _migrate_archives(self, guild_id: int, guild_dir: str):
        existing = await self._fetchall(
            "SELECT DISTINCT archive_year, archive_month FROM voice_stats_archive WHERE guild_id = ?",
            (guild_id,),
        )
        existing_pairs = {(row["archive_year"], row["archive_month"]) for row in existing}

        archive_sources = [guild_dir]
        legacy_root_dir = self._get_legacy_root_dir(guild_id)
        if legacy_root_dir and legacy_root_dir != guild_dir:
            archive_sources.append(legacy_root_dir)

        processed_pairs = set()
        for archive_source in archive_sources:
            if not os.path.isdir(archive_source):
                continue

            for filename in os.listdir(archive_source):
                match = ARCHIVE_FILE_RE.match(filename)
                if not match:
                    continue

                archive_year = int(match.group(1))
                archive_month = int(match.group(2))
                archive_pair = (archive_year, archive_month)
                if archive_pair in existing_pairs or archive_pair in processed_pairs:
                    continue

                file_path = os.path.join(archive_source, filename)
                data = self._read_json_file(file_path, {})
                rows = [
                    (guild_id, archive_year, archive_month, str(user_id), self._normalize_voice_total(value))
                    for user_id, value in (data or {}).items()
                ]
                if rows:
                    await self._conn.executemany(
                        """
                        INSERT OR REPLACE INTO voice_stats_archive
                        (guild_id, archive_year, archive_month, user_id, total_seconds)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    processed_pairs.add(archive_pair)

    def load_guild_config(self, guild_id: int) -> dict:
        return self._call(self._load_guild_config(guild_id))

    async def _load_guild_config(self, guild_id: int) -> dict:
        row = await self._fetchone(
            "SELECT * FROM guild_config WHERE guild_id = ?",
            (guild_id,),
        )
        if row is None:
            return {}

        channel_rows = await self._fetchall(
            "SELECT channel_id FROM guild_birthday_channels WHERE guild_id = ? ORDER BY position ASC",
            (guild_id,),
        )
        birthday_channel_ids = [channel_row["channel_id"] for channel_row in channel_rows]

        return {
            "birthday_channel_id": row["birthday_channel_id"],
            "birthday_channel_ids": birthday_channel_ids,
            "rank_category_id": row["rank_category_id"],
            "general_channel_id": row["general_channel_id"],
            "patch_notes_channel_id": row["patch_notes_channel_id"],
            "auto_shutdown_channel_id": row["auto_shutdown_channel_id"],
            "rank_role_ids": json.loads(row["rank_role_ids_json"]),
            "features": json.loads(row["features_json"]),
        }

    def save_guild_config(self, guild_id: int, config: dict):
        self._call(self._save_guild_config(guild_id, config))

    async def _save_guild_config(self, guild_id: int, config: dict):
        birthday_channel_ids = list(config.get("birthday_channel_ids") or [])
        primary_birthday_channel_id = birthday_channel_ids[0] if birthday_channel_ids else config.get("birthday_channel_id")

        await self._conn.execute(
            """
            INSERT INTO guild_config (
                guild_id,
                birthday_channel_id,
                rank_category_id,
                general_channel_id,
                patch_notes_channel_id,
                auto_shutdown_channel_id,
                rank_role_ids_json,
                features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                birthday_channel_id = excluded.birthday_channel_id,
                rank_category_id = excluded.rank_category_id,
                general_channel_id = excluded.general_channel_id,
                patch_notes_channel_id = excluded.patch_notes_channel_id,
                auto_shutdown_channel_id = excluded.auto_shutdown_channel_id,
                rank_role_ids_json = excluded.rank_role_ids_json,
                features_json = excluded.features_json
            """,
            (
                guild_id,
                primary_birthday_channel_id,
                config.get("rank_category_id"),
                config.get("general_channel_id"),
                config.get("patch_notes_channel_id"),
                config.get("auto_shutdown_channel_id"),
                json.dumps(config.get("rank_role_ids", []), ensure_ascii=False),
                json.dumps(config.get("features", {}), ensure_ascii=False),
            ),
        )
        await self._conn.execute(
            "DELETE FROM guild_birthday_channels WHERE guild_id = ?",
            (guild_id,),
        )
        if birthday_channel_ids:
            await self._conn.executemany(
                "INSERT INTO guild_birthday_channels (guild_id, channel_id, position) VALUES (?, ?, ?)",
                [
                    (guild_id, channel_id, position)
                    for position, channel_id in enumerate(birthday_channel_ids)
                ],
            )
        await self._conn.commit()

    def load_birthdays(self, guild_id: int) -> dict:
        return self._call(self._load_birthdays(guild_id))

    async def _load_birthdays(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT user_id, birthday FROM birthdays WHERE guild_id = ?",
            (guild_id,),
        )
        return {row["user_id"]: row["birthday"] for row in rows}

    def save_birthdays(self, guild_id: int, data: dict):
        self._call(self._save_birthdays(guild_id, data))

    async def _save_birthdays(self, guild_id: int, data: dict):
        await self._conn.execute("DELETE FROM birthdays WHERE guild_id = ?", (guild_id,))
        if data:
            await self._conn.executemany(
                "INSERT INTO birthdays (guild_id, user_id, birthday) VALUES (?, ?, ?)",
                [(guild_id, str(user_id), value) for user_id, value in data.items()],
            )
        await self._conn.commit()

    def load_voice_stats(self, guild_id: int) -> dict:
        return self._call(self._load_voice_stats(guild_id))

    async def _load_voice_stats(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT user_id, total_seconds FROM voice_stats WHERE guild_id = ?",
            (guild_id,),
        )
        return {row["user_id"]: row["total_seconds"] for row in rows}

    def save_voice_stats(self, guild_id: int, data: dict):
        self._call(self._save_voice_stats(guild_id, data))

    async def _save_voice_stats(self, guild_id: int, data: dict):
        await self._conn.execute("DELETE FROM voice_stats WHERE guild_id = ?", (guild_id,))
        if data:
            await self._conn.executemany(
                "INSERT INTO voice_stats (guild_id, user_id, total_seconds) VALUES (?, ?, ?)",
                [
                    (guild_id, str(user_id), self._normalize_voice_total(value))
                    for user_id, value in data.items()
                ],
            )
        await self._conn.commit()

    def load_competitors(self, guild_id: int) -> dict:
        return self._call(self._load_competitors(guild_id))

    async def _load_competitors(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT user_id, channel_id FROM competitors WHERE guild_id = ?",
            (guild_id,),
        )
        return {row["user_id"]: row["channel_id"] for row in rows}

    def save_competitors(self, guild_id: int, data: dict):
        self._call(self._save_competitors(guild_id, data))

    async def _save_competitors(self, guild_id: int, data: dict):
        await self._conn.execute("DELETE FROM competitors WHERE guild_id = ?", (guild_id,))
        rows = self._normalize_competitors(guild_id, data)
        if rows:
            await self._conn.executemany(
                "INSERT INTO competitors (guild_id, user_id, channel_id) VALUES (?, ?, ?)",
                rows,
            )
        await self._conn.commit()

    def load_entry_settings(self, guild_id: int) -> dict:
        return self._call(self._load_entry_settings(guild_id))

    async def _load_entry_settings(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT user_id, settings_json FROM entry_settings WHERE guild_id = ?",
            (guild_id,),
        )
        return {row["user_id"]: json.loads(row["settings_json"]) for row in rows}

    def save_entry_settings(self, guild_id: int, data: dict):
        self._call(self._save_entry_settings(guild_id, data))

    async def _save_entry_settings(self, guild_id: int, data: dict):
        await self._conn.execute("DELETE FROM entry_settings WHERE guild_id = ?", (guild_id,))
        if data:
            await self._conn.executemany(
                "INSERT INTO entry_settings (guild_id, user_id, settings_json) VALUES (?, ?, ?)",
                [
                    (guild_id, str(user_id), json.dumps(value, ensure_ascii=False))
                    for user_id, value in data.items()
                ],
            )
        await self._conn.commit()

    def load_state(self, guild_id: int) -> dict:
        return self._call(self._load_state(guild_id))

    async def _load_state(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT state_key, value_json FROM guild_state WHERE guild_id = ?",
            (guild_id,),
        )
        return {row["state_key"]: json.loads(row["value_json"]) for row in rows}

    def save_state(self, guild_id: int, data: dict):
        self._call(self._save_state(guild_id, data))

    async def _save_state(self, guild_id: int, data: dict):
        await self._conn.execute("DELETE FROM guild_state WHERE guild_id = ?", (guild_id,))
        if data:
            await self._conn.executemany(
                "INSERT INTO guild_state (guild_id, state_key, value_json) VALUES (?, ?, ?)",
                [
                    (guild_id, str(key), json.dumps(value, ensure_ascii=False))
                    for key, value in data.items()
                ],
            )
        await self._conn.commit()

    def get_guild_state(self, guild_id: int, key: str):
        return self._call(self._get_guild_state(guild_id, key))

    async def _get_guild_state(self, guild_id: int, key: str):
        row = await self._fetchone(
            "SELECT value_json FROM guild_state WHERE guild_id = ? AND state_key = ?",
            (guild_id, key),
        )
        return json.loads(row["value_json"]) if row else None

    def set_guild_state(self, guild_id: int, key: str, value):
        self._call(self._set_guild_state(guild_id, key, value))

    async def _set_guild_state(self, guild_id: int, key: str, value):
        await self._conn.execute(
            "INSERT OR REPLACE INTO guild_state (guild_id, state_key, value_json) VALUES (?, ?, ?)",
            (guild_id, key, json.dumps(value, ensure_ascii=False)),
        )
        await self._conn.commit()

    def append_chat_history(self, guild_id: int, speaker: str, content: str, limit: int):
        self._call(self._append_chat_history(guild_id, speaker, content, limit))

    async def _append_chat_history(self, guild_id: int, speaker: str, content: str, limit: int):
        await self._conn.execute(
            "INSERT INTO chat_history (guild_id, created_at, speaker, content) VALUES (?, ?, ?, ?)",
            (guild_id, datetime.now(timezone.utc).isoformat(), speaker, content),
        )
        await self._conn.execute(
            """
            DELETE FROM chat_history
            WHERE guild_id = ?
              AND id NOT IN (
                  SELECT id FROM chat_history
                  WHERE guild_id = ?
                  ORDER BY id DESC
                  LIMIT ?
              )
            """,
            (guild_id, guild_id, limit),
        )
        await self._conn.commit()

    def load_chat_history(self, guild_id: int, limit: int | None = None) -> list[str]:
        return self._call(self._load_chat_history(guild_id, limit))

    async def _load_chat_history(self, guild_id: int, limit: int | None = None) -> list[str]:
        sql = (
            "SELECT created_at, speaker, content FROM chat_history WHERE guild_id = ? ORDER BY id ASC"
            if limit is None
            else "SELECT created_at, speaker, content FROM chat_history WHERE guild_id = ? ORDER BY id DESC LIMIT ?"
        )
        params = (guild_id,) if limit is None else (guild_id, limit)
        rows = await self._fetchall(sql, params)
        if limit is not None:
            rows = list(reversed(rows))
        return [f"[{row['created_at']}] {row['speaker']}: {row['content']}" for row in rows]

    def load_voice_stats_archive(self, guild_id: int, archive_year: int, archive_month: int) -> dict:
        return self._call(self._load_voice_stats_archive(guild_id, archive_year, archive_month))

    async def _load_voice_stats_archive(self, guild_id: int, archive_year: int, archive_month: int) -> dict:
        rows = await self._fetchall(
            "SELECT user_id, total_seconds FROM voice_stats_archive WHERE guild_id = ? AND archive_year = ? AND archive_month = ?",
            (guild_id, archive_year, archive_month),
        )
        return {row["user_id"]: row["total_seconds"] for row in rows}

    def archive_voice_stats(self, guild_id: int, archive_year: int, archive_month: int, data: dict):
        self._call(self._archive_voice_stats(guild_id, archive_year, archive_month, data))

    async def _archive_voice_stats(self, guild_id: int, archive_year: int, archive_month: int, data: dict):
        await self._conn.execute(
            "DELETE FROM voice_stats_archive WHERE guild_id = ? AND archive_year = ? AND archive_month = ?",
            (guild_id, archive_year, archive_month),
        )
        if data:
            await self._conn.executemany(
                """
                INSERT INTO voice_stats_archive
                (guild_id, archive_year, archive_month, user_id, total_seconds)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (guild_id, archive_year, archive_month, str(user_id), self._normalize_voice_total(value))
                    for user_id, value in data.items()
                ],
            )
        await self._conn.commit()

    def load_all_time_voice_stats(self, guild_id: int) -> dict:
        return self._call(self._load_all_time_voice_stats(guild_id))

    async def _load_all_time_voice_stats(self, guild_id: int) -> dict:
        rows = await self._fetchall(
            """
            SELECT user_id, SUM(total_seconds) AS total_seconds
            FROM (
                SELECT user_id, total_seconds FROM voice_stats WHERE guild_id = ?
                UNION ALL
                SELECT user_id, total_seconds FROM voice_stats_archive WHERE guild_id = ?
            )
            GROUP BY user_id
            """,
            (guild_id, guild_id),
        )
        return {row["user_id"]: row["total_seconds"] for row in rows}

    # --- Channel Tracking Methods ---

    def load_tracked_channels(self, guild_id: int) -> list[int]:
        """Load list of tracked channel IDs."""
        return self._call(self._load_tracked_channels(guild_id))

    async def _load_tracked_channels(self, guild_id: int) -> list[int]:
        rows = await self._fetchall(
            "SELECT channel_id FROM tracked_voice_channels WHERE guild_id = ? AND enabled = 1",
            (guild_id,),
        )
        return [row["channel_id"] for row in rows]

    def add_tracked_channel(self, guild_id: int, channel_id: int):
        """Add a channel to tracking."""
        return self._call(self._add_tracked_channel(guild_id, channel_id))

    async def _add_tracked_channel(self, guild_id: int, channel_id: int):
        await self._conn.execute(
            "INSERT OR REPLACE INTO tracked_voice_channels (guild_id, channel_id, enabled, created_at) VALUES (?, ?, 1, ?)",
            (guild_id, channel_id, int(time.time())),
        )
        await self._conn.commit()

    def remove_tracked_channel(self, guild_id: int, channel_id: int):
        """Remove a channel from tracking."""
        return self._call(self._remove_tracked_channel(guild_id, channel_id))

    async def _remove_tracked_channel(self, guild_id: int, channel_id: int):
        await self._conn.execute(
            "DELETE FROM tracked_voice_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        await self._conn.commit()

    def load_channel_voice_stats(self, guild_id: int, channel_id: int, period: str) -> float:
        """Load total seconds for a channel in a period."""
        return self._call(self._load_channel_voice_stats(guild_id, channel_id, period))

    async def _load_channel_voice_stats(self, guild_id: int, channel_id: int, period: str) -> float:
        row = await self._fetchone(
            "SELECT total_user_seconds FROM channel_voice_stats WHERE guild_id = ? AND channel_id = ? AND period = ?",
            (guild_id, channel_id, period),
        )
        return row["total_user_seconds"] if row else 0.0

    def save_channel_voice_stats(self, guild_id: int, channel_id: int, period: str, total_seconds: float):
        """Save channel stats for a period."""
        return self._call(self._save_channel_voice_stats(guild_id, channel_id, period, total_seconds))

    async def _save_channel_voice_stats(self, guild_id: int, channel_id: int, period: str, total_seconds: float):
        await self._conn.execute(
            "INSERT OR REPLACE INTO channel_voice_stats (guild_id, channel_id, period, total_user_seconds) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, period, total_seconds),
        )
        await self._conn.commit()

    def add_to_channel_stats(self, guild_id: int, channel_id: int, period: str, seconds: float):
        """Add seconds to channel stats."""
        return self._call(self._add_to_channel_stats(guild_id, channel_id, period, seconds))

    async def _add_to_channel_stats(self, guild_id: int, channel_id: int, period: str, seconds: float):
        current = await self._load_channel_voice_stats(guild_id, channel_id, period)
        await self._save_channel_voice_stats(guild_id, channel_id, period, current + seconds)

    def reset_channel_stats_for_period(self, guild_id: int, period: str):
        """Reset all channel stats for a period to 0."""
        return self._call(self._reset_channel_stats_for_period(guild_id, period))

    async def _reset_channel_stats_for_period(self, guild_id: int, period: str):
        await self._conn.execute(
            "DELETE FROM channel_voice_stats WHERE guild_id = ? AND period = ?",
            (guild_id, period),
        )
        await self._conn.commit()

    def archive_channel_stats(self, guild_id: int, archive_year: int, archive_month: int, channel_id: int, total_seconds: float):
        """Archive channel stats for a month."""
        return self._call(self._archive_channel_stats(guild_id, archive_year, archive_month, channel_id, total_seconds))

    async def _archive_channel_stats(self, guild_id: int, archive_year: int, archive_month: int, channel_id: int, total_seconds: float):
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO channel_voice_stats_archive
            (guild_id, channel_id, archive_year, archive_month, total_user_seconds)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, channel_id, archive_year, archive_month, total_seconds),
        )
        await self._conn.commit()

    def load_all_time_channel_stats(self, guild_id: int, channel_id: int) -> float:
        """Load all-time total seconds for a channel."""
        return self._call(self._load_all_time_channel_stats(guild_id, channel_id))

    async def _load_all_time_channel_stats(self, guild_id: int, channel_id: int) -> float:
        row = await self._fetchone(
            """
            SELECT SUM(total_user_seconds) AS total_seconds
            FROM (
                SELECT total_user_seconds FROM channel_voice_stats WHERE guild_id = ? AND channel_id = ?
                UNION ALL
                SELECT total_user_seconds FROM channel_voice_stats_archive WHERE guild_id = ? AND channel_id = ?
            )
            """,
            (guild_id, channel_id, guild_id, channel_id),
        )
        return row["total_seconds"] if row and row["total_seconds"] else 0.0

    # --- Economy Methods ---

    def get_balance(self, guild_id: int, user_id: int) -> float:
        return self._call(self._get_balance(guild_id, user_id))

    async def _get_balance(self, guild_id: int, user_id: int) -> float:
        row = await self._fetchone(
            "SELECT coins FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return row["coins"] if row else 0.0

    def add_coins(self, guild_id: int, user_id: int, amount: float) -> float:
        return self._call(self._add_coins(guild_id, user_id, amount))

    async def _add_coins(self, guild_id: int, user_id: int, amount: float) -> float:
        await self._conn.execute(
            """INSERT INTO economy_accounts (guild_id, user_id, coins) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET coins = coins + ?""",
            (guild_id, user_id, amount, amount),
        )
        await self._conn.commit()
        row = await self._fetchone(
            "SELECT coins FROM economy_accounts WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return row["coins"] if row else amount

    def spend_coins(self, guild_id: int, user_id: int, amount: float) -> bool:
        return self._call(self._spend_coins(guild_id, user_id, amount))

    async def _spend_coins(self, guild_id: int, user_id: int, amount: float) -> bool:
        balance = await self._get_balance(guild_id, user_id)
        if balance < amount:
            return False
        await self._conn.execute(
            "UPDATE economy_accounts SET coins = coins - ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        await self._conn.commit()
        return True

    def add_purchase(self, guild_id: int, user_id: int, month: str, ptype: str, value: float):
        self._call(self._add_purchase(guild_id, user_id, month, ptype, value))

    async def _add_purchase(self, guild_id: int, user_id: int, month: str, ptype: str, value: float):
        await self._conn.execute(
            """INSERT INTO economy_purchases (guild_id, user_id, month, purchase_type, purchase_value)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id, month, purchase_type)
               DO UPDATE SET purchase_value = purchase_value + ?""",
            (guild_id, user_id, month, ptype, value, value),
        )
        await self._conn.commit()

    def get_purchase(self, guild_id: int, user_id: int, month: str, ptype: str) -> float:
        return self._call(self._get_purchase(guild_id, user_id, month, ptype))

    async def _get_purchase(self, guild_id: int, user_id: int, month: str, ptype: str) -> float:
        row = await self._fetchone(
            "SELECT purchase_value FROM economy_purchases WHERE guild_id = ? AND user_id = ? AND month = ? AND purchase_type = ?",
            (guild_id, user_id, month, ptype),
        )
        return row["purchase_value"] if row else 0.0

    def get_all_purchases(self, guild_id: int, user_id: int, month: str) -> dict:
        return self._call(self._get_all_purchases(guild_id, user_id, month))

    async def _get_all_purchases(self, guild_id: int, user_id: int, month: str) -> dict:
        rows = await self._fetchall(
            "SELECT purchase_type, purchase_value FROM economy_purchases WHERE guild_id = ? AND user_id = ? AND month = ?",
            (guild_id, user_id, month),
        )
        return {row["purchase_type"]: row["purchase_value"] for row in rows}

    def clear_purchases(self, guild_id: int):
        self._call(self._clear_purchases(guild_id))

    async def _clear_purchases(self, guild_id: int):
        await self._conn.execute(
            "DELETE FROM economy_purchases WHERE guild_id = ?",
            (guild_id,),
        )
        await self._conn.commit()

    def get_coin_leaderboard(self, guild_id: int, limit: int = 10) -> list:
        return self._call(self._get_coin_leaderboard(guild_id, limit))

    async def _get_coin_leaderboard(self, guild_id: int, limit: int = 10) -> list:
        rows = await self._fetchall(
            "SELECT user_id, coins FROM economy_accounts WHERE guild_id = ? ORDER BY coins DESC LIMIT ?",
            (guild_id, limit),
        )
        return [(int(row["user_id"]), round(row["coins"], 1)) for row in rows]

    async def _run_migrations(self):
        """Apply schema migrations for tables that may already exist."""
        try:
            await self._conn.execute("ALTER TABLE guild_config ADD COLUMN patch_notes_channel_id INTEGER")
        except Exception:
            pass

    # ── Event CRUD ──────────────────────────────────────────────────────

    def add_event(self, guild_id: int, event_type: str, scope: str, value: float,
                  starts_at: str, ends_at: str, reason: str = "") -> int:
        return self._call(self._add_event(guild_id, event_type, scope, value, starts_at, ends_at, reason))

    async def _add_event(self, guild_id: int, event_type: str, scope: str, value: float,
                         starts_at: str, ends_at: str, reason: str = "") -> int:
        cursor = await self._conn.execute(
            """INSERT INTO economy_events (guild_id, event_type, scope, value, starts_at, ends_at, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, event_type, scope, value, starts_at, ends_at, reason),
        )
        await self._conn.commit()
        return cursor.lastrowid

    def get_active_custom_events(self, guild_id: int, now_iso: str) -> list:
        return self._call(self._get_active_custom_events(guild_id, now_iso))

    async def _get_active_custom_events(self, guild_id: int, now_iso: str) -> list:
        rows = await self._fetchall(
            """SELECT id, guild_id, event_type, scope, value, starts_at, ends_at, reason
               FROM economy_events
               WHERE guild_id IN (0, ?) AND active = 1 AND starts_at <= ? AND ends_at >= ?""",
            (guild_id, now_iso, now_iso),
        )
        return [dict(row) for row in rows]

    def deactivate_event(self, event_id: int):
        self._call(self._deactivate_event(event_id))

    async def _deactivate_event(self, event_id: int):
        await self._conn.execute(
            "UPDATE economy_events SET active = 0 WHERE id = ?",
            (event_id,),
        )
        await self._conn.commit()

    def deactivate_guild_events(self, guild_id: int):
        self._call(self._deactivate_guild_events(guild_id))

    async def _deactivate_guild_events(self, guild_id: int):
        await self._conn.execute(
            "UPDATE economy_events SET active = 0 WHERE guild_id = ? AND active = 1",
            (guild_id,),
        )
        await self._conn.commit()

    def get_all_events_for_guild(self, guild_id: int) -> list:
        return self._call(self._get_all_events_for_guild(guild_id))

    async def _get_all_events_for_guild(self, guild_id: int) -> list:
        rows = await self._fetchall(
            """SELECT id, guild_id, event_type, scope, value, starts_at, ends_at, reason, active
               FROM economy_events
               WHERE guild_id IN (0, ?)
               ORDER BY starts_at DESC""",
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def _fetchone(self, sql: str, params=()):
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, sql: str, params=()):
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchall()


    def _get_migration_file_path(self, guild_id: int, guild_dir: str, filename: str) -> str:
        guild_path = os.path.join(guild_dir, filename)
        if os.path.exists(guild_path):
            return guild_path

        legacy_path = self._get_legacy_root_file_path(guild_id, filename)
        if legacy_path:
            logging.info("Using legacy root file for guild %s migration: %s", guild_id, legacy_path)
            return legacy_path

        return guild_path

    def _get_legacy_root_dir(self, guild_id: int) -> str | None:
        legacy_guild_id = os.getenv("GUILD_ID", "").strip()
        if legacy_guild_id and legacy_guild_id != str(guild_id):
            return None
        if not legacy_guild_id:
            return None
        return self.base_dir

    def _get_legacy_root_file_path(self, guild_id: int, filename: str) -> str | None:
        legacy_root_dir = self._get_legacy_root_dir(guild_id)
        if not legacy_root_dir:
            return None

        legacy_path = os.path.join(legacy_root_dir, filename)
        if os.path.exists(legacy_path):
            return legacy_path

        return None

    @staticmethod
    def _read_json_file(path: str, default):
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                return json.load(handle)
        except Exception:
            return default

    @staticmethod
    def _normalize_voice_total(value) -> float:
        if isinstance(value, dict):
            value = value.get("total", 0)
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    @staticmethod
    def _normalize_competitors(guild_id: int, data) -> list[tuple[int, str, int | None]]:
        if isinstance(data, list):
            return [(guild_id, str(user_id), None) for user_id in data]
        if isinstance(data, dict):
            return [(guild_id, str(user_id), channel_id) for user_id, channel_id in data.items()]
        return []