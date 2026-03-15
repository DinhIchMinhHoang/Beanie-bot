# Beanie Bot - Architecture Documentation

## Table of Contents
- [System Overview](#system-overview)
- [Class Diagram](#class-diagram)
- [Sequence Diagrams](#sequence-diagrams)
- [Data Flow](#data-flow)

---

## System Overview

Beanie Bot is a multi-feature Discord bot built with:
- **discord.py** - Discord API wrapper
- **SQLite** - Persistent data storage
- **Google GenAI** - AI chat functionality
- **Azure SDK** - Cloud infrastructure management
- **Python 3.12** - Runtime

### Architecture Layers

```
┌─────────────────────────────────────┐
│   Discord Bot Layer (main.py)       │
│   Command Tree & Event Handlers     │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   Feature Modules (features/*.py)   │
│  - VoiceTracking                    │
│  - Birthday Management              │
│  - Minecraft Server                 │
│  - AI Chat                          │
│  - Admin                            │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   Core Layer (core/*.py)            │
│  - Storage (SQLite Backend)         │
│  - Guild Config Management          │
│  - Bot Configuration                │
└────────────────┬────────────────────┘
                 │
┌────────────────▼────────────────────┐
│   Data Persistence                  │
│  - SQLite Database (beanie.sqlite3) │
│  - Legacy JSON Files (migration)    │
└─────────────────────────────────────┘
```

---

## Class Diagram

```mermaid
classDiagram
    class BotConfig {
        +DISCORD_TOKEN: str
        +GUILD_ID: int
        +OPENAI_API_KEY: str
        +storage: SQLiteStorage
        +guild_manager: GuildConfigManager
        +get_storage()
        +ensure_guild_setup()
        +ensure_guild_resources()
    }

    class SQLiteStorage {
        -base_dir: str
        -db_path: str
        -conn: aiosqlite.Connection
        +ensure_guild_initialized()
        +load_guild_config()
        +save_guild_config()
        +load_voice_stats()
        +save_voice_stats()
        +load_all_time_voice_stats()
        +load_birthdays()
        +save_birthdays()
        -_migrate_simple_json_table()
        -_migrate_chat_history()
        -_migrate_archives()
        -_get_migration_file_path()
    }

    class GuildConfig {
        -guild_id: str
        -base_dir: str
        -_config: dict
        +get_guild_config()
        +set_rank_category_id()
        +get_rank_category_id()
        +set_birthday_channel_ids()
        +get_birthday_channel_ids()
        +get_rank_role_ids()
        +set_rank_role_ids()
        -_load_guild_config()
        -_save_guild_config()
    }

    class VoiceTrackingFeature {
        -bot: discord.Bot
        -config: BotConfig
        -ffmpeg_exec: str
        +load_voice_stats()
        +save_voice_stats()
        +load_all_time_stats()
        +load_competitors()
        +save_competitors()
        +get_rank_info()
        +checkpoint_voice_stats()
        +apply_rank_roles_to_guild()
        +on_voice_state_update()
        +rank_cmd()
        +say_cmd()
        +sync_roles_cmd()
    }

    class BirthdayFeature {
        -bot: discord.Bot
        -config: BotConfig
        +load_birthdays()
        +save_birthdays()
        +birthday_cmd()
        +birthday_channel_cmd()
        +check_birthdays()
    }

    class MinecraftFeature {
        -bot: discord.Bot
        -config: BotConfig
        -compute_client: ComputeManagementClient
        +status_cmd()
        +start_cmd()
        +stop_cmd()
        +restart_mc_cmd()
    }

    class AIChat {
        -bot: discord.Bot
        -client: genai.Client
        +on_message()
        +chat()
    }

    class GuildConfigManager {
        -configs: dict
        +get_guild_config()
        +ensure_guild_setup()
        +ensure_discord_resources()
    }

    BotConfig --> SQLiteStorage
    BotConfig --> GuildConfigManager
    GuildConfigManager --> GuildConfig
    VoiceTrackingFeature --> BotConfig
    VoiceTrackingFeature --> SQLiteStorage
    BirthdayFeature --> BotConfig
    MinecraftFeature --> BotConfig
    AIChat --> BotConfig
```

---

## Sequence Diagrams

### 1. Bot Startup Sequence

```mermaid
sequenceDiagram
    participant User
    participant Discord as Discord API
    participant Bot as Beanie Bot
    participant Storage as SQLiteStorage
    participant Config as GuildConfig
    participant Features as Features

    User->>Discord: Invite bot to guild
    Discord->>Bot: on_guild_join event
    Bot->>Storage: initialize()
    Storage->>Storage: create SQLite schema
    Bot->>Config: ensure_guild_setup()
    Config->>Storage: ensure_guild_initialized()
    Storage->>Storage: migrate JSON to SQLite
    Bot->>Features: load_features()
    Features->>Bot: Register all cogs
    Bot->>Discord: tree.sync() commands
    Discord->>User: Commands available
```

### 2. Voice Time Tracking Sequence

```mermaid
sequenceDiagram
    participant Member
    participant Discord as Discord API
    participant VoiceTrack as VoiceTracking
    participant Storage as SQLiteStorage
    participant DB as SQLite DB

    Member->>Discord: Join voice channel
    Discord->>VoiceTrack: on_voice_state_update(before, after)
    VoiceTrack->>Storage: load_voice_stats(guild_id)
    Storage->>DB: SELECT voice_stats
    DB-->>Storage: current stats
    Storage-->>VoiceTrack: stats dict
    VoiceTrack->>VoiceTrack: calculate elapsed time
    VoiceTrack->>Storage: save_voice_stats(guild_id)
    Storage->>DB: INSERT/UPDATE voice_stats
    Note over VoiceTrack: Periodic role sync (hourly)
    VoiceTrack->>VoiceTrack: apply_rank_roles_to_guild()
    VoiceTrack->>Discord: Apply rank roles to members
    Member->>Member: Receives new rank role
```

### 3. /rank Command Flow

```mermaid
sequenceDiagram
    participant User
    participant Discord as Discord API
    participant Bot as Beanie Bot
    participant Storage as SQLiteStorage
    participant DB as SQLite DB

    User->>Discord: /rank add
    Discord->>Bot: rank_cmd(action='add')
    Bot->>Storage: load_competitors(guild_id)
    Storage->>DB: SELECT * FROM competitors
    Bot->>Storage: load_voice_stats(guild_id)
    DB-->>Bot: user already registered?
    alt User not in competition
        Bot->>Discord: create_voice_channel()
        Discord-->>Bot: new channel ID
        Bot->>Storage: save_competitors(guild_id)
        Storage->>DB: INSERT INTO competitors
        Bot->>User: ✅ You joined!
    else User already registered
        Bot->>User: ⚠️ Already a competitor
    end
```

### 4. Birthday Check Sequence

```mermaid
sequenceDiagram
    participant Clock
    participant BirthdayTask as Birthday Task
    participant Storage as SQLiteStorage
    participant DB as SQLite DB
    participant Discord as Discord API
    participant Guild as Guild Channel

    Clock->>BirthdayTask: [Daily at 00:00 UTC]
    BirthdayTask->>Storage: load_birthdays(guild_id)
    Storage->>DB: SELECT * FROM birthdays
    DB-->>BirthdayTask: birthdates
    loop For each birthday today
        BirthdayTask->>Discord: fetch_user(user_id)
        BirthdayTask->>Guild: Send birthday message
        Guild->>Guild: Display birthday wish
    end
```

---

## Data Flow

### Voice Tracking Data Flow

```
Discord Event (voice state change)
    ↓
on_voice_state_update() handler
    ↓
checkpoint_voice_stats()
    ├→ SQLite: Load current voice_stats
    ├→ Calculate elapsed time
    └→ SQLite: Update voice_stats
    ↓
Hourly: update_leaderboard()
    ├→ Load current month stats
    └→ Update voice channel names
    ↓
Monthly: monthly_reset_check()
    ├→ Archive previous month stats
    └→ Reset current month stats
    ↓
Commands: /rank list
    ├→ Load all-time stats (current + archived)
    └→ Display leaderboard
```

### Data Persistence Flow

```
Application Startup
    ↓
SQLiteStorage._initialize()
    ├→ Open/Create beanie.sqlite3
    ├→ Create schema if missing
    └→ Set WAL mode for concurrency
    ↓
GuildConfig._load_guild_config()
    ├→ Check SQLite for existing config
    ├→ If missing: Check legacy JSON files
    └→ Migrate JSON → SQLite (if needed)
    ↓
Load/Save Data
    ├→ All reads from SQLite
    ├→ All writes to SQLite
    └→ Legacy JSON files remain for rollback
```

---

## Module Dependencies

```
main.py
├── core.config.BotConfig
│   ├── core.storage.SQLiteStorage
│   └── core.guild_config.GuildConfigManager
├── features.voice_track.VoiceTrackingFeature
├── features.birthday.BirthdayFeature
├── features.minecraft.MinecraftFeature
├── features.ai_chat.AIChat
└── features.admin.AdminFeature

core/storage.py
├── aiosqlite (async SQLite)
└── json (legacy file format)

core/guild_config.py
├── core.storage.SQLiteStorage
└── discord.py

features/voice_track.py
├── discord.py
├── core.config.BotConfig
├── gtts (text-to-speech)
└── discord.opus (audio codec)

features/birthday.py
├── discord.py
└── core.config.BotConfig

features/minecraft.py
├── discord.py
├── azure.identity (authentication)
├── azure.mgmt.compute (VM management)
├── mcstatus (server polling)
└── mcrcon (RCON commands)

features/ai_chat.py
├── discord.py
├── google.genai (Gemini API)
└── openai (OpenAI API)
```

---

## Error Handling & Recovery

```
┌─────────────────────────────────┐
│  Exception Occurs               │
└────────────┬────────────────────┘
             │
    ┌────────▼────────┐
    │  Logging Layer  │
    │  - Log error    │
    │  - Stack trace  │
    └────────┬────────┘
             │
    ┌────────▼─────────────────────┐
    │  Error Type Check            │
    └┬────────────┬────────────────┘
     │            │
  ┌──▼──┐    ┌────▼─────┐
  │Cmd  │    │System    │
  │Error│    │Error     │
  │     │    │          │
  │Reply│    │Retry/    │
  │User │    │Fallback  │
  └─────┘    └──────────┘
```

