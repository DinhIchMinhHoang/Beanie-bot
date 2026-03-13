# Beanie Bot - Refactored Structure

## Overview

Beanie Bot has been refactored into a modular architecture with separated feature modules for better maintainability and organization.

## Project Structure

```
beanie-bot/
├── main.py                 # Main entry point - bot initialization and feature loading
├── core/                   # Core utilities and configuration
│   ├── __init__.py
│   └── config.py          # BotConfig class with all configuration constants
├── features/               # Feature modules (pluggable components)
│   ├── __init__.py
│   ├── ai_chat.py         # AI chat functionality with Gemini
│   ├── voice_track.py     # Voice tracking, rankings, birthdays, entrance sounds
│   ├── minecraft.py       # Minecraft server management and Azure VM control
│   └── admin.py           # Administrative commands and utilities
├── data/                   # Data storage directory
│   └── sfx/               # Sound effects and TTS files
├── requirements.txt        # Python dependencies
└── .env                   # Environment variables (not in git)
```

## Feature Modules

### 1. AI Chat (`features/ai_chat.py`)
- **Features:**
  - AI chat with Gemini (via `/beanie` command)
  - Chat memory management
  - Cooldown and lockdown system
  - `/wipe` command to clear memory

- **Key Classes:**
  - `AIChatFeature`: Main cog handling AI chat

### 2. Voice Tracking (`features/voice_track.py`)
- **Features:**
  - Voice time tracking for admins
  - Birthday management and automatic wishes
  - Ranking system (Iron → Legendary)
  - Leaderboard with voice channels
  - Monthly statistics reset with Hall of Fame
  - Text-to-speech (`/say` command for Gold+ ranks)
  - Custom entrance sounds (Diamond+ ranks)
  - `/rank`, `/birthday`, `/say`, `/entry` command groups

- **Key Classes:**
  - `VoiceTrackingFeature`: Main cog for voice tracking
  - `EntryCommandsGroup`: /entry command group for entrance sounds
  - `EntryCustomizeView`, `EntryTTSModal`: UI components

### 3. Minecraft Management (`features/minecraft.py`)
- **Features:**
  - Azure VM control (start/stop/status)
  - SSH command execution
  - RCON support for Minecraft commands
  - Auto-shutdown when server is empty
  - Player count tracking
  - `/status`, `/start`, `/stop`, `/restart_mc` commands

- **Key Classes:**
  - `MinecraftFeature`: Main cog for server management

### 4. Admin (`features/admin.py`)
- **Features:**
  - Administrative utilities (extensible)

- **Key Classes:**
  - `AdminFeature`: Main cog for admin commands

## Configuration

All configuration is centralized in `core/config.py` as a `BotConfig` class:

- Discord settings (token, guild ID, channel IDs)
- API keys (Gemini)
- Azure credentials
- SSH/Minecraft server settings
- RCON configuration
- File paths for data persistence
- Rank role IDs
- Birthday messages

## Main Entry Point (`main.py`)

The main.py now handles:
1. FFmpeg setup and validation
2. Logging configuration
3. Azure client initialization
4. Gemini client setup
5. Discord bot initialization
6. Feature module loading via `load_features()`
7. Command tree synchronization
8. Bot execution

## How Features are Loaded

Features are loaded as Discord.py Cogs in the `load_features()` async function:

```python
async def load_features():
    from features.ai_chat import AIChatFeature
    from features.minecraft import MinecraftFeature
    from features.voice_track import VoiceTrackingFeature, EntryCommandsGroup
    from features.admin import AdminFeature
    
    # Initialize cogs with required dependencies
    ai_chat = AIChatFeature(bot, gemini_client, BotConfig)
    await bot.add_cog(ai_chat)
    
    minecraft = MinecraftFeature(bot, compute_client, BotConfig)
    await bot.add_cog(minecraft)
    
    voice_tracking = VoiceTrackingFeature(bot, FFMPEG_EXEC, BotConfig)
    await bot.add_cog(voice_tracking)
    
    entry_group = EntryCommandsGroup(bot, voice_tracking)
    await bot.add_cog(entry_group)
    
    admin = AdminFeature(bot, BotConfig)
    await bot.add_cog(admin)
```

## Data Persistence

Each feature manages its own data files:

- **AI Chat:** `chat_history.txt`
- **Voice Tracking:**
  - `birthdays.json`
  - `voice_stats.json`
  - `competitors.json`
  - `entry_settings.json`
  - `state.json`
  - `archive_YYYY_MM.json` (monthly archives)
- **Minecraft:** `last_request_channel.txt`
- **Logs:** `beanie.log` (auto-trimmed to 200 lines)

## Benefits of This Architecture

1. **Modularity:** Each feature is self-contained and can be developed/tested independently
2. **Maintainability:** Code is organized by functionality, making it easier to find and fix issues
3. **Scalability:** New features can be added as separate modules without touching existing code
4. **Testability:** Individual features can be tested in isolation
5. **Reusability:** Feature modules can potentially be reused in other bots
6. **Clarity:** Clear separation of concerns makes the codebase easier to understand

## Running the Bot

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables in .env file
# DISCORD_TOKEN=...
# GEMINI_API_KEY=...
# (and other required variables)

# Run the bot
python main.py
```

## Development Guidelines

### Adding a New Feature

1. Create a new file in `features/` directory (e.g., `features/new_feature.py`)
2. Define a Cog class that inherits from `commands.Cog`
3. Implement your feature's commands and event handlers
4. Add initialization code in `load_features()` in main.py
5. Pass required dependencies (bot, config, clients) to your feature's constructor

### Modifying Configuration

- Add new configuration constants to `core/config.py` in the `BotConfig` class
- Access via `self.config.CONSTANT_NAME` in feature modules

## Migration Notes

- The original `main.py` has been backed up as `main.py.backup`
- All functionality has been preserved and reorganized
- No breaking changes to user-facing commands
- Data files remain in the same format and location

## Testing

After refactoring, verify:
1. Bot starts without errors
2. All slash commands are synced and visible
3. AI chat (`/beanie`) works
4. Voice tracking records time correctly
5. Entrance sounds play for Diamond+ users
6. Minecraft server commands work (`/start`, `/stop`, `/status`)
7. Admin commands are accessible

## Troubleshooting

If features fail to load:
1. Check import statements in `load_features()`
2. Verify all dependencies are installed
3. Check for syntax errors with: `python -m py_compile features/*.py`
4. Review logs in `beanie.log`

## Future Enhancements

Potential improvements:
- Add more admin commands to `features/admin.py`
- Create a `features/moderation.py` for moderation tools
- Add a `features/fun.py` for entertainment commands
- Implement feature hot-reloading for development
- Add unit tests for each feature module
