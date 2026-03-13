# Multi-Guild Support Migration Guide

## Overview
The Beanie Bot has been refactored to support multiple Discord guilds (servers) simultaneously. Each guild now has its own isolated data storage for birthdays, voice stats, AI chat memory, and other features.

## Architecture Changes

### 1. Guild-Specific Data Structure
```
data/
├── guilds/
│   ├── {guild_id_1}/
│   │   ├── birthdays.json
│   │   ├── voice_stats.json
│   │   ├── competitors.json
│   │   ├── entry_settings.json
│   │   ├── state.json
│   │   ├── chat_history.txt
│   │   └── guild_config.json
│   ├── {guild_id_2}/
│   │   └── ...
│   └── ...
└── sfx/
    ├── {user_id}.mp3          # Global entrance sounds
    ├── custom_{user_id}.mp3   # Custom user sounds (work across all guilds)
    └── temp_*.mp3             # Temporary TTS files
```

### 2. New Core Components

#### `core/guild_config.py` (NEW)
- **GuildConfig**: Manages per-guild configuration and file paths
  - Properties: birthday_file, voice_stats_file, competitors_file, etc.
  - Methods: get_birthday_channel_id(), set_birthday_channel_id(), etc.
  - Default configuration with sensible defaults
  
- **GuildConfigManager**: Factory for creating/retrieving GuildConfig instances
  - Singleton pattern for efficient memory usage
  - Automatic guild directory creation

#### `core/config.py` (UPDATED)
- Added `guild_manager = GuildConfigManager()` 
- Added `get_guild_config(guild_id)` method
- Added `ensure_guild_setup(guild_id)` method
- Kept global constants (API keys, timezones, etc.)

### 3. Feature Updates

#### Birthday Feature (`features/birthday.py`)
**Changes:**
- `load_birthdays(guild_id)` - Now takes guild_id parameter
- `save_birthdays(guild_id, data)` - Guild-specific save
- `birthday_check()` - Loops through all guilds
- Birthday commands now extract `guild_id = interaction.guild.id`

#### AI Chat Feature (`features/ai_chat.py`)
**Changes:**
- Per-guild memory: `self.chat_memory = {}` (dict by guild_id)
- Per-guild lockdown: `self.lockdown = {}`, `self.lockdown_until = {}`
- Per-guild queues: `self.ai_queues = {}`
- `add_to_memory(guild_id, user, content)` - Saves to guild-specific chat_history.txt
- `process_guild_queue(guild_id)` - Processes AI requests per guild
- `cooldown_check()` - Checks all guilds for lockdown expiry

#### Voice Tracking Feature (`features/voice_track.py`)
**Major Changes:**
- All data methods now take guild_id parameter:
  - `load_voice_stats(guild_id)`, `save_voice_stats(guild_id, data)`
  - `load_competitors(guild_id)`, `save_competitors(guild_id, data)`
  - `load_entry_settings(guild_id)`, `save_entry_settings(guild_id, data)`
  - `load_state(guild_id)`, `save_state(guild_id, data)`
  
- Updated methods:
  - `checkpoint_voice_stats(guild_id)` - Checkpoints for specific guild
  - `apply_rank_roles_to_guild(guild)` - Uses guild-specific data and role IDs
  
- Background tasks now loop through guilds:
  - `update_leaderboard()` - Updates leaderboards for all guilds
  - `monthly_reset_check()` - Performs resets per guild
  - `periodic_role_sync()` - Already had guild loop
  
- Event handlers updated:
  - `on_voice_state_update()` - Extracts `guild_id = member.guild.id`
  
- All commands updated:
  - `/sync_roles`, `/refresh_leaderboard`, `/rank`, `/say`
  - `/entry on`, `/entry off`, `/entry add`, `/entry upload`
  - All extract `guild_id = interaction.guild.id`

#### Main Bot (`main.py`)
**Changes:**
- `on_ready()` - Ensures guild setup for all existing guilds
- `on_guild_join()` (NEW) - Automatically sets up new guild directories

## Guild Configuration

Each guild has a `guild_config.json` with the following structure:

```json
{
  "features": {
    "birthday_enabled": true,
    "voice_tracking_enabled": true,
    "ai_chat_enabled": true
  },
  "birthday_channel_id": null,
  "rank_category_id": null,
  "general_channel_id": null,
  "rank_role_ids": []
}
```

### Setting Guild-Specific Configs

```python
# Get guild config
guild_config = bot_config.get_guild_config(guild_id)

# Set birthday channel
guild_config.set_birthday_channel_id(123456789)

# Set rank category
guild_config.set_rank_category_id(987654321)

# Set rank role IDs (Iron, Bronze, Silver, Gold, etc.)
role_ids = [1475819335514849391, 1475808729705353290, ...]
guild_config.set_rank_role_ids(role_ids)
```

## Migration Path

### For Existing Single-Guild Deployments

1. **Automatic migration on first run:**
   - Bot will create `data/guilds/{guild_id}/` directory
   - Old files in root will remain for backward compatibility
   - No data loss - old files are not deleted

2. **Manual data migration (optional):**
   ```bash
   # Move existing data to guild-specific folder
   GUILD_ID=123456789012345678
   mkdir -p "data/guilds/$GUILD_ID"
   mv birthdays.json "data/guilds/$GUILD_ID/"
   mv voice_stats.json "data/guilds/$GUILD_ID/"
   mv competitors.json "data/guilds/$GUILD_ID/"
   mv entry_settings.json "data/guilds/$GUILD_ID/"
   mv state.json "data/guilds/$GUILD_ID/"
   mv chat_history.txt "data/guilds/$GUILD_ID/" 2>/dev/null || true
   ```

3. **Configure guild settings:**
   - Use admin commands or edit `guild_config.json` directly
   - Set birthday_channel_id, rank_category_id, general_channel_id
   - Set rank_role_ids array

### For New Guild Deployments

1. **Automatic setup:**
   - When bot joins a guild, `on_guild_join()` creates directory structure
   - Default config is created automatically

2. **Configure channels and roles:**
   - Admin sets birthday channel: Use birthday commands
   - Admin sets rank category: Edit guild_config.json or use future admin commands
   - Admin sets rank role IDs: Edit guild_config.json

## Global vs Guild-Specific Data

### Global Data (Shared Across All Guilds)
- **Entrance sounds:** `data/sfx/{user_id}.mp3`
  - User's custom entrance sound works in all guilds
  - Managed via `GuildConfig.get_user_sfx_path(user_id)` classmethod

### Guild-Specific Data
- **Birthdays:** Each guild tracks its own birthdays
- **Voice stats:** Time tracked separately per guild
- **Competitors:** Voice competition participants per guild
- **AI chat memory:** Each guild has separate chat history
- **Entry settings:** Entrance sound on/off per guild
- **State:** Monthly reset tracking per guild

## Testing Changes

Update test fixtures to include guild_id:

```python
# Example test update
def test_load_birthdays(mock_config):
    guild_id = 999888777666555  # Test guild ID
    birthdays = load_birthdays(guild_id)
    assert isinstance(birthdays, dict)
```

## API Changes Summary

### Core API
```python
# Old (single guild)
config.BIRTHDAYS_FILE
config.VOICE_STATS_FILE

# New (multi-guild)
guild_config = config.get_guild_config(guild_id)
guild_config.birthday_file
guild_config.voice_stats_file
```

### Feature Methods
```python
# Old
load_birthdays()
save_birthdays(data)

# New
load_birthdays(guild_id)
save_birthdays(guild_id, data)
```

### Commands
```python
# All commands now extract guild_id
@app_commands.command(name="rank")
async def rank_cmd(self, interaction: discord.Interaction, ...):
    guild_id = interaction.guild.id
    guild_config = self.config.get_guild_config(guild_id)
    # ... use guild_config
```

## Future Enhancements

1. **Admin commands for guild config:**
   - `/guild config set birthday_channel #channel`
   - `/guild config set rank_category #category`
   - `/guild config set rank_roles @role1 @role2 ...`

2. **Migration helper command:**
   - `/admin migrate` - Migrate old single-guild data

3. **Guild statistics:**
   - `/stats guild` - Show guild-specific stats
   - `/stats global` - Show cross-guild statistics

4. **Backup/restore per guild:**
   - `/backup guild` - Backup guild data
   - `/restore guild` - Restore from backup

## Troubleshooting

### Issue: Commands not working after update
**Solution:** Ensure guild directories exist - restart bot to trigger `on_ready()` setup

### Issue: Old data not visible
**Solution:** Manually migrate data to guild-specific folders (see migration steps above)

### Issue: Rank roles not syncing
**Solution:** Check guild_config.json has correct rank_role_ids array

### Issue: Birthday channel not found
**Solution:** Set birthday_channel_id in guild_config.json or use birthday setup command

## Rollback Plan

If issues occur, rollback is possible:

1. Keep backup of old files (birthdays.json, voice_stats.json, etc.)
2. Code is backward compatible - old file paths still work if guild structure fails
3. Git revert to previous commit if needed

## Notes

- **No breaking changes for existing single-guild deployments**
- **Entrance sounds remain global** - users get same sound in all guilds
- **Automatic setup** - no manual intervention needed for new guilds
- **Backward compatible** - old file paths are preserved as fallback
- **Memory efficient** - guild configs loaded on-demand
