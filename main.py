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
        if BotConfig.GUILD_ID:
            guild_obj = discord.Object(id=BotConfig.GUILD_ID)
            try:
                await tree.copy_global_to(guild=guild_obj)
            except Exception:
                pass
            synced = await tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} commands to guild {BotConfig.GUILD_ID}.")
        else:
            synced = await tree.sync()
            print(f"Synced {len(synced)} global commands.")
        
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

