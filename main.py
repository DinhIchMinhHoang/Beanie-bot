"""
Beanie Bot - Main Entry Point
A Discord bot with AI chat, voice tracking, and Minecraft server management features
"""

import os
import subprocess
import shutil
import logging
import discord
from discord.ext import commands
from google import genai
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient

# Import configuration
from core.config import BotConfig


# Anchor paths to the repository root (folder containing main.py).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --- FFmpeg Auto-Setup ---
def check_and_setup_ffmpeg():
    """Check for working ffmpeg and try to install if needed."""
    # Try multiple ffmpeg locations
    ffmpeg_paths = [
        os.getenv("FFMPEG_EXEC"),
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        os.path.join(os.getcwd(), "bin", "ffmpeg"),
        os.path.join(os.getcwd(), "ffmpeg"),
        shutil.which("ffmpeg")
    ]
    
    # Test each path
    for path in ffmpeg_paths:
        if path and os.path.exists(path):
            try:
                # Try to run ffmpeg -version
                result = subprocess.run(
                    [path, "-version"],
                    capture_output=True,
                    timeout=5,
                    text=True
                )
                if result.returncode == 0:
                    print(f"[OK] Found working ffmpeg at: {path}")
                    print(f"   Version: {result.stdout.split(chr(10))[0]}")
                    return path
                else:
                    print(f"[WARN] FFmpeg at {path} returned error code {result.returncode}")
            except Exception as e:
                print(f"[WARN] FFmpeg at {path} failed to run: {e}")
    
    # If no working ffmpeg found, try to install via apt
    print("[ERROR] No working ffmpeg found. Attempting to install via apt...")
    try:
        # Try apt-get install
        subprocess.run(
            ["apt-get", "update"],
            capture_output=True,
            timeout=60
        )
        result = subprocess.run(
            ["apt-get", "install", "-y", "ffmpeg"],
            capture_output=True,
            timeout=120
        )
        if result.returncode == 0:
            print("[OK] Successfully installed ffmpeg via apt-get")
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                return system_ffmpeg
    except Exception as e:
        print(f"[WARN] Could not install ffmpeg via apt: {e}")
    
    # Last resort: use system path
    print("[WARN] Using fallback: /usr/bin/ffmpeg (may not work)")
    return "/usr/bin/ffmpeg"


FFMPEG_EXEC = check_and_setup_ffmpeg()


# --- Logging Setup (with auto-trim) ---
class MemoryLimitFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        try:
            with open(self.baseFilename, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > BotConfig.MEMORY_LIMIT:
                lines = lines[-BotConfig.MEMORY_LIMIT:]
                with open(self.baseFilename, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        except Exception:
            pass


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        MemoryLimitFileHandler(os.path.join(BASE_DIR, "beanie.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)


# --- Azure Setup ---
compute_client = None
if (BotConfig.AZURE_SUBSCRIPTION_ID and BotConfig.AZURE_CLIENT_ID and 
    BotConfig.AZURE_CLIENT_SECRET and BotConfig.AZURE_TENANT_ID):
    try:
        _cred = ClientSecretCredential(
            tenant_id=BotConfig.AZURE_TENANT_ID,
            client_id=BotConfig.AZURE_CLIENT_ID,
            client_secret=BotConfig.AZURE_CLIENT_SECRET,
        )
        compute_client = ComputeManagementClient(_cred, BotConfig.AZURE_SUBSCRIPTION_ID)
    except Exception as e:
        logging.warning(f"Azure client init failed: {e}")


# --- External Service Setup ---
gemini_client = genai.Client(api_key=BotConfig.GEMINI_API_KEY)


# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree


# --- Load Feature Modules ---
async def load_features():
    """Load all feature modules as cogs."""
    try:
        # Import feature modules
        from features.ai_chat import AIChatFeature
        from features.minecraft import MinecraftFeature
        from features.voice_track import VoiceTrackingFeature, EntryCommandsGroup
        from features.birthday import BirthdayFeature
        from features.admin import AdminFeature
        
        # Initialize and add AI Chat feature
        ai_chat = AIChatFeature(bot, gemini_client, BotConfig)
        await bot.add_cog(ai_chat)
        logging.info("Loaded AI Chat feature")
        
        # Initialize and add Minecraft feature
        minecraft = MinecraftFeature(bot, compute_client, BotConfig)
        await bot.add_cog(minecraft)
        logging.info("Loaded Minecraft feature")
        
        # Initialize and add Voice Tracking feature
        voice_tracking = VoiceTrackingFeature(bot, FFMPEG_EXEC, BotConfig)
        await bot.add_cog(voice_tracking)
        logging.info("Loaded Voice Tracking feature")
        
        # Add entry commands group
        entry_group = EntryCommandsGroup(bot, voice_tracking)
        await bot.add_cog(entry_group)
        logging.info("Loaded Entry commands group")
        
        # Initialize and add Birthday feature
        birthday = BirthdayFeature(bot, BotConfig)
        await bot.add_cog(birthday)
        logging.info("Loaded Birthday feature")
        
        # Initialize and add Admin feature
        admin = AdminFeature(bot, BotConfig)
        await bot.add_cog(admin)
        logging.info("Loaded Admin feature")
        
    except Exception as e:
        logging.error(f"Failed to load features: {e}", exc_info=True)


# --- Help Command ---
@tree.command(name="help", description="Show all available commands and bot features")
async def help_command(interaction: discord.Interaction):
    """Display comprehensive help information about Beanie Bot."""
    help_text = """
# 🤖 **BEANIE BOT - COMMAND HELP**

## 🎤 **VOICE TRACKING & RANKING**
Command `/rank [action]` - Manage voice time competition
• **add** - Join the competition (or add another user as admin)
• **remove** - Leave the competition (or remove user as admin)
• **list** - View all-time leaderboard with total hours

💎 **Premium Features** (earn hours to unlock ranks):
• **Gold+**: `/say [message]` - Make Beanie speak in voice (max 50 chars)
• **Diamond+**: `/on` / `/off` - Enable/disable entrance sounds
• **Immortal+**: `/add` / `/upload` - Custom entrance sounds

Admin Commands:
• `/sync_roles` - Manually sync rank roles and roles for all members
• `/refresh_leaderboard` - Force update voice channel names now

---

## 🎂 **BIRTHDAY MANAGEMENT** (Admin Commands)
• `/birthday add [user] [dd/mm]` - Register a user's birthday
• `/birthday list` - See all registered birthdays

• `/birthday_channel set [channel]` - Set birthday announcement channel
• `/birthday_channel add [channel]` - Add another announcement channel
• `/birthday_channel remove [channel]` - Remove an announcement channel
• `/birthday_channel list` - View all announcement channels

---

## 🎮 **MINECRAFT SERVER** (Azure VM Management)
• `/status` - Check Azure VM and Minecraft server status
• `/start` - Start Azure VM and launch Minecraft server
• `/stop` - Stop Minecraft server and deallocate VM (saves costs)
• `/restart_mc` - Restart Minecraft server only

---

## 📊 **RANKING SYSTEM**
As you spend time in voice channels, you earn ranks with special perks:
1. **Bronze** - Basic member
2. **Silver** - Unlocks at ~10 hours
3. **Gold** - Unlocks at ~50 hours + `/say` command
4. **Platinum** - Unlocks at ~100 hours
5. **Diamond** - Unlocks at ~200 hours + entrance sounds
6. **Immortal** - Unlocks at ~500 hours + custom sounds
7. **Godly** - Unlocks at ~1000+ hours

---

## ✨ **FEATURES**
✅ Automatic voice time tracking
✅ Monthly leaderboard in rank category
✅ Birthday reminders and announcements
✅ Minecraft server management with Azure integration
✅ Multi-guild support
✅ Customizable entrance sounds

---

**Type `/help` anytime to see this message again!**
"""
    
    await interaction.response.send_message(help_text, ephemeral=True)


# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot is ready."""
    print(f"Logged in as {bot.user}")

    try:
        BotConfig.get_storage()
    except Exception as e:
        logging.error(f"Failed to initialize SQLite storage: {e}")
    
    # Create sfx directory if it doesn't exist
    os.makedirs("data/sfx", exist_ok=True)
    
    # Ensure guild directories exist for all guilds
    for guild in bot.guilds:
        try:
            BotConfig.ensure_guild_setup(guild.id)
            await BotConfig.ensure_guild_resources(guild)
            logging.info(f"Ensured guild setup for {guild.name} ({guild.id})")
        except Exception as e:
            logging.error(f"Failed to setup guild {guild.id}: {e}")
    
    # Cleanup orphaned TTS files from previous sessions
    try:
        for filename in os.listdir("data/sfx"):
            if filename.startswith("tts_"):
                file_path = os.path.join("data/sfx", filename)
                try:
                    os.remove(file_path)
                    logging.info(f"Cleaned up orphaned file: {filename}")
                except Exception as e:
                    logging.warning(f"Failed to delete {filename}: {e}")
    except Exception as e:
        logging.warning(f"Failed to cleanup data/sfx folder: {e}")
    
    # Load feature modules
    await load_features()
    
    # Sync commands
    try:
        synced_global = await tree.sync()
        print(f"Synced {len(synced_global)} global commands.")

        for guild in bot.guilds:
            try:
                synced_guild = await tree.sync(guild=discord.Object(id=guild.id))
                print(f"Synced {len(synced_guild)} commands to guild {guild.id}.")
            except Exception as e:
                logging.warning(f"Guild command sync failed for {guild.id}: {e}")

        try:
            cmds = [c.name for c in tree.get_commands()]
            print(f"App commands registered in tree: {cmds}")
        except Exception:
            pass
    except Exception as e:
        print(f"Sync error: {e}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    """Called when the bot joins a new guild."""
    try:
        BotConfig.ensure_guild_setup(guild.id)
        await BotConfig.ensure_guild_resources(guild)
        logging.info(f"Bot joined new guild: {guild.name} ({guild.id}) - Guild directory structure created")
    except Exception as e:
        logging.error(f"Failed to setup new guild {guild.id}: {e}")


# --- Main Entry Point ---
if __name__ == "__main__":
    bot.run(BotConfig.DISCORD_TOKEN)

