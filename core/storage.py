"""SQLite-backed persistence for Beanie Bot."""

import asyncio
import json
import logging
import os
import re
import threading
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
                auto_shutdown_channel_id,
                rank_role_ids_json,
                features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                birthday_channel_id = excluded.birthday_channel_id,
                rank_category_id = excluded.rank_category_id,
                general_channel_id = excluded.general_channel_id,
                auto_shutdown_channel_id = excluded.auto_shutdown_channel_id,
                rank_role_ids_json = excluded.rank_role_ids_json,
                features_json = excluded.features_json
            """,
            (
                guild_id,
                primary_birthday_channel_id,
                config.get("rank_category_id"),
                config.get("general_channel_id"),
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