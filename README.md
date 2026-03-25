# 🤖 Beanie Bot - A Multi-Feature Discord Bot

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.7.1-blue.svg)](https://discordpy.readthedocs.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A powerful, production-ready Discord bot built with Python, featuring voice time tracking, birthday management, Minecraft server control, and AI-powered chat capabilities.

---

## 📋 Table of Contents

- [Features](#-features)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Architecture](#-architecture)
- [Database Schema](#-database-schema)
- [CI/CD Pipeline](#-cicd-pipeline)
- [Development](#-development)
- [Contributing](#-contributing)
- [Troubleshooting](#-troubleshooting)
- [License](#-license)

---

## ✨ Features

### 🎤 Voice Time Tracking & Ranking System
Track how much time users spend in voice channels and assign ranks based on activity.

- **Automatic Tracking**: Logs voice time per user per month
- **9-Tier Ranking System**: Iron → Bronze → Silver → Gold → Platinum → Diamond → Elite → Immortal → Legendary
- **Monthly Leaderboard**: Voice channel name updates showing top speakers
- **All-Time Statistics**: Combined historical data from all months
- **Premium Perks**:
  - **Gold+**: Text-to-speech in voice channels (`/say`)
  - **Diamond+**: Custom entrance sounds
  - **Immortal+**: Upload custom audio files

**Commands**:
```
/rank add              - Join the voice competition
/rank list             - View all-time leaderboard
/rank remove           - Leave the competition
/say [message]         - Make bot speak (Gold+ rank)
/on | /off            - Toggle entrance sounds (Diamond+ rank)
/add [file] | /upload - Custom entrance sound (Immortal+ rank)
```

### 📊 Channel Voice Tracking (Admin)
Monitor total voice activity per channel with automatic name updates.

- **Channel Monitoring**: Track cumulative voice time for any voice channel
- **Automatic Display**: Channel names update with format: `Channel Name・XXh` (e.g., `gaming・125h`)
- **All-Time Totals**: Persists across monthly resets via archive storage
- **Monthly Reset**: Automatically archives previous month and starts fresh
- **Admin Control**: Manually adjust stats if needed

**Commands**:
```
/channel add [channel_id]      - Start tracking a voice channel
/channel remove [channel_id]   - Stop tracking and cleanup
/channel list                  - View all-time total hours per channel
/channel edit [channel_id] [hours] - Manually set hours (Admin only)
```

**How it works**:
- Tracks user joins/leaves in real-time
- Updates channel names every 5 minutes
- Saves stats hourly and archives monthly
- Displays format: `#gaming・24h` (channel name + total hours)

### 🎂 Birthday Management
Automate birthday reminders and announcements.

- **Birthday Registration**: Add user birthdays in `dd/mm` format
- **Automatic Reminders**: Posts daily at midnight UTC
- **Multiple Channels**: Support multiple announcement channels
- **Admin Controls**: Add/remove/list birthdays and channels

**Commands**:
```
/birthday add [user] [dd/mm]           - Register birthday
/birthday list                          - View all registered birthdays
/birthday_channel set/add/remove/list   - Manage announcement channels
```

### 🎮 Minecraft Server Management
Control Azure-hosted Minecraft server directly from Discord.

- **VM Lifecycle Management**: Start/stop/restart via Discord
- **Cost Optimization**: Deallocate Azure VM when not in use
- **Server Status**: Check if server is running
- **RCON Integration**: Execute commands on Minecraft server

**Commands**:
```
/status                 - Check VM and server status
/start                  - Start Azure VM and Minecraft server
/stop                   - Stop server and deallocate VM (saves costs)
/restart_mc             - Restart Minecraft server only
```

### 💬 AI Chat
Intelligent conversation powered by Gemini and OpenAI APIs.

- **Multi-Model Support**: Gemini and OpenAI models
- **Context Awareness**: Learns from conversation history
- **Mentions**: Reply to `@BeanieBot` in chat
- **DM Support**: Direct message the bot for private chats

### 🛡️ Admin Tools
Server administration helpers.

- Guild configuration management
- User permission controls
- Moderation helpers

### 📊 Help System
Comprehensive `/help` command showing all features.

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.12+**
- **Discord Bot Token** (from Discord Developer Portal)
- **APIs** (optional):
  - OpenAI API key
  - Google Gemini API key
  - Azure credentials (for Minecraft feature)

### 1. Clone Repository
```bash
git clone https://github.com/BeanBot/beanie-bot.git
cd beanie-bot
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\Activate.ps1  # Windows PowerShell
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env with your tokens and API keys
```

### 5. Run Bot
```bash
python main.py
```

---

## 📦 Installation

### System Requirements
- **OS**: Linux, macOS, or Windows
- **Python**: 3.12+
- **Memory**: 512MB+
- **Disk**: 500MB+
- **Network**: Stable internet connection

### Detailed Setup

#### Step 1: Clone Repository
```bash
git clone https://github.com/BeanBot/beanie-bot.git
cd beanie-bot
```

#### Step 2: Python Environment
```bash
# Create virtual environment
python3.12 -m venv .venv

# Activate it
source .venv/bin/activate          # Linux/macOS
# or
.venv\Scripts\Activate.ps1         # Windows PowerShell
```

#### Step 3: Install Dependencies
```bash
# Core dependencies
pip install -r requirements.txt

# Development dependencies (optional)
pip install -r requirements-dev.txt
```

#### Step 4: Get Discord Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create New Application
3. Go to "Bot" section and create a bot
4. Copy the token

#### Step 5: Create `.env` File
```bash
cp .env.example .env
nano .env  # Edit with your credentials
```

**Required Variables**:
```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here
```

**Optional Variables**:
```env
OPENAI_API_KEY=sk-...
GOOGLE_GENAI_KEY=...
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
AZURE_SUBSCRIPTION_ID=...
```

#### Step 6: Invite Bot to Server
Generate invite URL from Developer Portal with these scopes:
- `bot` (scope)
- `applications.commands` (scope)

Permissions needed:
- `Send Messages`
- `Read Messages/View Channels`
- `Manage Channels`
- `Manage Roles`
- `Connect` (Voice)
- `Speak` (Voice)
- `Use Voice Activity`

#### Step 7: Run Bot
```bash
python main.py
```

Expected output:
```
Logged in as BeanieBot#1234
Synced 15 global commands.
Bot is ready!
```

---

## ⚙️ Configuration

### Environment Variables

#### Core Configuration
```bash
DISCORD_TOKEN              # Bot token from Discord Developer Portal (required)
GUILD_ID                   # Primary guild/server ID (optional, for single-guild)
BEANIE_BASE_DIR            # Project root directory (auto-detected if omitted)
```

#### AI Features
```bash
OPENAI_API_KEY             # OpenAI API key for chat
GOOGLE_GENAI_KEY           # Google Gemini API key for chat
```

#### Azure (Minecraft Server)
```bash
AZURE_TENANT_ID            # Azure AD tenant ID
AZURE_CLIENT_ID            # Service principal client ID
AZURE_CLIENT_SECRET        # Service principal secret
AZURE_SUBSCRIPTION_ID      # Azure subscription ID
MINECRAFT_RESOURCE_GROUP   # Azure resource group name
MINECRAFT_VM_NAME          # Azure VM name
```

#### Performance Tuning
```bash
MEMORY_LIMIT=10000         # Max log file lines before trimming
VOICE_STAT_CHECKPOINT_INTERVAL=60  # Seconds between checkpoints
```

### Guild-Specific Configuration

Stored in SQLite database:
```json
{
  "birthday_channel_id": 1054049999475965972,
  "rank_category_id": 1472493127934677185,
  "general_channel_id": 1475806362393907282,
  "rank_role_ids": [1475819335514849391, 1475808729705353290, ...],
  "features": {"voice_tracking": true, "birthdays": true, ...}
}
```

---

## 📖 Usage

### Core Commands

#### Getting Help
```
/help                      - Show all available commands
```

#### Voice Tracking
```
/rank add                  - Join voice competition
/rank remove               - Leave competition
/rank list                 - View leaderboard (all-time)
/sync_roles (admin)        - Manually sync rank roles
/refresh_leaderboard (admin) - Update leaderboard channel names
```

#### Premium Commands (Rank-Gated)
```
/say "message"             - Text-to-speech (Gold+)
/on                        - Enable entrance sounds (Diamond+)
/off                       - Disable entrance sounds (Diamond+)
/add                       - Add entrance sound from URL (Immortal+)
/upload                    - Upload entrance sound file (Immortal+)
```

#### Birthday Management (Admin)
```
/birthday add @user dd/mm  - Register birthday
/birthday list             - View all birthdays
/birthday_channel set #channel      - Set primary announcement channel
/birthday_channel add #channel      - Add backup announcement channel
/birthday_channel list              - View all announcement channels
```

#### Minecraft Server (Owner)
```
/status                    - Check server status
/start                     - Start VM and server
/stop                      - Stop server and deallocate VM
/restart_mc                - Restart just Minecraft
```

#### AI Chat
```
@BeanieBot hello           - Chat in channel (mention)
DM: hello                  - Chat via direct message
```

### Permission Levels

| Command | Required Permission | Details |
|---------|-------------------|---------|
| `/rank add` | None | Can add themselves, admins can add others |
| `/rank remove` | None | Can remove themselves, admins can remove others |
| `/birthday` | Admin | Only admins can register birthdays |
| `/status` | Owner | Minecraft commands reserved for server owner |
| `/say` | Gold+ Rank | Premium feature unlock |
| `/on`/`/off` | Diamond+ Rank | Premium feature unlock |

---

## 🏗️ Architecture

### Project Structure
```
beanie-bot/
├── main.py              # Entry point, event handlers, command routing
├── core/
│   ├── config.py        # BotConfig, global configuration
│   ├── storage.py       # SQLiteStorage, data persistence
│   └── guild_config.py  # GuildConfig, per-guild configuration
├── features/
│   ├── voice_track.py   # VoiceTrackingFeature, ranking system
│   ├── birthday.py      # BirthdayFeature, birthday management
│   ├── minecraft.py     # MinecraftFeature, server control
│   ├── ai_chat.py       # AIChat, AI conversation
│   └── admin.py         # AdminFeature, admin tools
├── tests/
│   ├── test_storage.py
│   ├── test_voice_track.py
│   ├── test_birthday.py
│   └── ... (8 test modules)
├── data/
│   ├── beanie.sqlite3   # Main database (SQLite WAL mode)
│   ├── guilds/          # Legacy JSON files (migration)
│   └── sfx/             # Sound effects cache
├── docs/
│   ├── ARCHITECTURE.md  # UML class & sequence diagrams
│   ├── DATABASE.md      # Database schema & relationships
│   └── CICD.md          # CI/CD pipeline details
├── requirements.txt     # Python dependencies
└── pytest.ini          # Test configuration
```

### Dependency Diagram
```
discord.py                    [Core Discord API]
  ├── aiosqlite              [Async SQLite access]
  ├── google-genai           [Google Gemini AI]
  ├── openai                 [OpenAI API]
  ├── gtts                   [Text-to-speech]
  ├── azure-identity         [Azure authentication]
  ├── azure-mgmt-compute     [Azure VM management]
  ├── paramiko               [SSH client]
  ├── mcrcon                 [Minecraft RCON]
  ├── mcstatus               [Minecraft status check]
  └── python-dotenv          [Environment variables]

pytest                        [Testing framework]
pytest-asyncio              [Async test support]
```

For detailed architecture, see [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 📊 Database Schema

Beanie Bot uses **SQLite** with automatic migration from JSON files.

### Main Tables
```
guild_config              - Guild configuration & resource IDs
guild_birthday_channels   - Birthday announcement channels
birthdays                 - User birthdays
voice_stats              - Current month voice time
voice_stats_archive      - Historical voice time
competitors              - Voice competition members
entry_settings           - User entrance sound settings
guild_state              - Flexible KV store
chat_history             - Message logs
```

### Example: Voice Stats Table
```sql
CREATE TABLE voice_stats (
    guild_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    total_seconds REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
```

For full schema documentation, see [DATABASE.md](docs/DATABASE.md).

---

## 🔄 CI/CD Pipeline

### Automated Workflows
- **On Every Push**: Run tests (48 unit tests)
- **On Every Push**: Lint code (Pylint, Black)
- **On Main Branch**: Deploy to production if tests pass

### Test Coverage
```
✅ 48 Total Tests
   - storage.py           8 tests
   - voice_track.py      17 tests
   - birthday.py         12 tests
   - guild_config.py      6 tests
   - config.py            3 tests
   - ai_chat.py           2 tests
```

### Manual Deployment
```bash
git push origin main
# → GitHub Actions runs tests
# → On success, auto-deploys to VM
```

### Rollback
```bash
git reset --hard HEAD~1
git push origin main
```

For detailed CI/CD info, see [CICD.md](docs/CICD.md).

---

## 👨‍💻 Development

### Setting Up Development Environment

#### 1. Clone and Install
```bash
git clone https://github.com/BeanBot/beanie-bot.git
cd beanie-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

#### 2. Create Feature Branch
```bash
git checkout -b feature/your-feature-name
```

#### 3. Make Changes
- Edit code in `features/`, `core/`, or other modules
- Write tests in `tests/`

#### 4. Run Local Tests
```bash
pytest tests/ -v
```

Expected output:
```
tests/test_storage.py::TestSQLiteStorage::test_ensure_guild_initialized PASSED
tests/test_voice_track.py::TestVoiceTrackingFeature::test_rank_cmd_add_self PASSED
...
48 passed in 0.45s
```

#### 5. Check Code Quality
```bash
pylint core/ features/ --disable=all --enable=syntax-error
black --check core/ features/
```

#### 6. Commit and Push
```bash
git add -A
git commit -m "feat: your feature description"
git push origin feature/your-feature-name
```

#### 7. Create Pull Request
Open PR on GitHub with description of changes.

### Running Tests Locally

#### All Tests
```bash
pytest tests/
```

#### Specific Module
```bash
pytest tests/test_voice_track.py -v
```

#### Single Test
```bash
pytest tests/test_voice_track.py::TestVoiceTrackingFeature::test_rank_cmd_add_self -v
```

#### With Coverage
```bash
pytest --cov=core --cov=features tests/
```

### Code Style
- **Black**: Auto-format code
- **Pylint**: Check for errors
- **isort**: Organize imports

```bash
black core/ features/ tests/
isort core/ features/ tests/
pylint core/ features/ --disable=all --enable=syntax-error
```

### Development Tips
1. Use `logging` module for debugging
2. Write tests for new features
3. Update docstrings
4. Keep commits atomic
5. Follow PEP 8 style guide

---

## 🐛 Troubleshooting

### Common Issues

#### Bot Won't Start
```bash
# Check if token is valid
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('DISCORD_TOKEN'))"

# Check Python version
python --version  # Should be 3.12+

# Check dependencies
pip list | grep discord

# Run with debug logging
DISCORD_PY_LOG_LEVEL=DEBUG python main.py
```

#### Commands Not Showing
```bash
# Sync commands manually (in code):
await tree.sync()
await tree.sync(guild=discord.Object(id=guild_id))

# Check bot permissions (needs Administrator or specific perms)
# - applications.commands scope
# - Send Messages
# - Manage Roles
```

#### Database Issues
```bash
# Backup database
cp data/beanie.sqlite3 data/beanie.sqlite3.backup

# Check database integrity
sqlite3 data/beanie.sqlite3 "PRAGMA integrity_check;"

# View table structure
sqlite3 data/beanie.sqlite3 ".schema guild_config"
```

#### Voice Tracking Not Working
```bash
# Ensure user is in voice channel
# Check voice_stats in database:
sqlite3 data/beanie.sqlite3 "SELECT * FROM voice_stats WHERE guild_id=YOUR_GUILD_ID"

# Verify rank_category_id is set:
sqlite3 data/beanie.sqlite3 "SELECT * FROM guild_config WHERE guild_id=YOUR_GUILD_ID"
```

#### FFmpeg Issues (for TTS)
```bash
# Install ffmpeg
sudo apt-get install ffmpeg  # Linux
brew install ffmpeg          # macOS
# Windows: Download from ffmpeg.org

# Verify installation
ffmpeg -version

# Set in .env if custom path
FFMPEG_EXEC=/usr/bin/ffmpeg
```

### Performance Issues

#### High CPU Usage
- Check if bot is stuck in loop (`journalctl -u beanie-bot`)
- Increase voice stat checkpoint interval
- Consider reducing log verbosity

#### Memory Leaks
- Monitor with `htop`
- Check for infinite loops in event handlers
- Ensure `gc.collect()` is called periodically

### Connection Issues

#### Timeout Errors
```bash
# Check network connectivity
ping discord.com

# Increase timeout (in code):
bot.rest.timeout = 30  # seconds
```

#### SSL Certificate Errors
```bash
# Install ca-certificates
pip install --upgrade certifi

# Force SSL verification
export PYTHONHTTPSVERIFY=1
```

### Getting Help

1. **Check Logs**:
```bash
journalctl -u beanie-bot -n 100
# or on Windows:
type beanie.log
```

2. **Search Issues**: https://github.com/BeanBot/beanie-bot/issues

3. **Discord Support**: https://discord.gg/... (if available)

---

## 📝 Contributing

Contributions are welcome! Please follow these steps:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Code Standards
- Follow PEP 8
- Add tests for new features
- Update docstrings
- Write clear commit messages
- Update README if needed

### Testing Requirements
All code must:
- Pass all 48 existing tests
- Have test coverage for new features
- Pass linting checks
- Have no syntax errors

---

## 📋 Project Status

### Completed ✅
- [x] Voice time tracking with ranking
- [x] Birthday management system
- [x] Minecraft server control via Azure
- [x] AI chat (Gemini & OpenAI)
- [x] SQLite migration from JSON
- [x] Multi-guild support
- [x] Comprehensive test suite (48 tests)
- [x] CI/CD pipeline
- [x] `/help` command
- [x] Full documentation

### In Progress 🔄
- [ ] SonarQube code quality metrics
- [ ] Automated database backups

### Planned 🚀
- [ ] Admin dashboard web interface
- [ ] Custom moderation rules
- [ ] Music playback (YouTube integration)
- [ ] Reaction roles
- [ ] Ticket system
- [ ] Analytics dashboard

---

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **discord.py**: Discord API wrapper
- **Google Gemini**: AI chat model
- **OpenAI**: ChatGPT integration
- **Azure**: Cloud infrastructure
- All contributors and testers

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/BeanBot/beanie-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/BeanBot/beanie-bot/discussions)
- **Email**: [support email if available]

---

## 🎉 Getting Started

Run `/help` in your Discord server to see all available commands!

```
🤖 BEANIE BOT - COMMAND HELP

🎤 VOICE TRACKING & RANKING
/rank add | /rank list | /say | /on | /off

🎂 BIRTHDAY MANAGEMENT  
/birthday add | /birthday list | /birthday_channel

🎮 MINECRAFT SERVER
/status | /start | /stop | /restart_mc

📊 LEADERBOARDS & STATS
/rank list (all-time) | Monthly voice channels

✨ More features shown with /help
```

Happy botting! 🚀

---

**Last Updated**: March 15, 2026
**Version**: 1.0.0
**Status**: Production Ready ✅

