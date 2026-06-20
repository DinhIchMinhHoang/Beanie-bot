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
        from features.channel_track import ChannelTrackingFeature
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
        
        # Initialize and add Channel Tracking feature
        channel_tracking = ChannelTrackingFeature(bot, BotConfig)
        await bot.add_cog(channel_tracking)
        logging.info("Loaded Channel Tracking feature")
        
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
    
    # Split help into multiple embeds to avoid message length limit
    embeds = []
    
    # Embed 1: Header and Voice Tracking
    embed1 = discord.Embed(
        title="🤖 BEANIE BOT - COMMAND HELP",
        description="Complete guide to all commands and features",
        color=discord.Color.blue()
    )
    embed1.add_field(
        name="🎤 VOICE TRACKING & RANKING",
        value="Command `/rank [action]` - Manage voice time competition\n"
              "• **add** - Join the competition\n"
              "• **remove** - Leave the competition\n"
              "• **list** - View all-time leaderboard\n"
              "• **set [user] [seconds]** - Set user's voice hours (admin only)\n\n"
              "💎 **Premium Features**:\n"
              "• **Gold+**: `/say [message]` - Beanie speaks in voice\n"
              "• **Diamond+**: `/on` / `/off` - Entrance sounds\n"
              "• **Immortal+**: `/add` / `/upload` - Custom sounds",
        inline=False
    )
    embed1.add_field(
        name="📊 CHANNEL TRACKING (Admin)",
        value="Command `/channel [action]` - Track voice activity time per channel\n"
              "• **add [channel_id]** - Start tracking a voice channel\n"
              "• **remove [channel_id]** - Stop tracking a voice channel\n"
              "• **list** - View all-time total hours per channel\n"
              "• **edit [channel_id] [hours]** - Manually set channel hours (admin)\n\n"
              "⏱️ Tracks channel occupancy: Time from first user join to last user leave\n"
              "📈 Channel names automatically display: `Channel Name・XXh`",
        inline=False
    )
    embed1.add_field(
        name="�🔧 Admin Commands",
        value="• `/sync_roles` - Sync rank roles for all members\n"
              "• `/refresh_leaderboard` - Force update leaderboard channels\n"
              "• `/admin_force_reset` - Manually trigger monthly reset (testing)",
        inline=False
    )
    embeds.append(embed1)
    
    # Embed 2: AI Chat
    embed_ai = discord.Embed(
        title="🤖 AI CHAT WITH BEANIE",
        description="Talk to the AI-powered Beanie bot",
        color=discord.Color.purple()
    )
    embed_ai.add_field(
        name="Chat Commands",
        value="• `/beanie [message]` - Chat with Beanie AI\n"
              "  → Message-based interaction with memory\n"
              "  → Beanie remembers conversation context\n"
              "  → Responds in Vietnamese or English\n\n"
              "• `/wipe` - Clear Beanie's memory (Admin only)",
        inline=False
    )
    embed_ai.add_field(
        name="⚙️ How It Works",
        value="💬 Each guild has its own memory\n"
              "⏳ 1-hour cooldown after 50 messages\n"
              "🔒 Cooldown resets memory automatically",
        inline=False
    )
    embeds.append(embed_ai)
    
    # Embed 3: Birthday Management
    embed2 = discord.Embed(
        title="🎂 BIRTHDAY MANAGEMENT",
        description="Admin Commands",
        color=discord.Color.magenta()
    )
    embed2.add_field(
        name="User Birthdays",
        value="• `/birthday add [user] [dd/mm]` - Register birthday\n"
              "• `/birthday list` - See all registered birthdays",
        inline=False
    )
    embed2.add_field(
        name="Announcement Channels",
        value="• `/birthday_channel set [channel]` - Set announcement channel\n"
              "• `/birthday_channel add [channel]` - Add channel\n"
              "• `/birthday_channel remove [channel]` - Remove channel\n"
              "• `/birthday_channel list` - View all channels",
        inline=False
    )
    embeds.append(embed2)
    
    # Embed 4: Minecraft & Features
    embed3 = discord.Embed(
        title="🎮 MINECRAFT & FEATURES",
        color=discord.Color.green()
    )
    embed3.add_field(
        name="🎮 MINECRAFT SERVER",
        value="• `/status` - Check VM and server status\n"
              "• `/start` - Start VM and launch server\n"
              "• `/stop` - Stop server and deallocate VM\n"
              "• `/restart_mc` - Restart server only",
        inline=False
    )
    embed3.add_field(
        name="✨ Features",
        value="✅ Automatic voice time tracking\n"
              "✅ Monthly leaderboard\n"
              "✅ Birthday reminders\n"
              "✅ Minecraft Azure management\n"
              "✅ Multi-guild support\n"
              "✅ Custom entrance sounds",
        inline=False
    )
    embeds.append(embed3)
    
    # Embed 5: Ranking System
    embed4 = discord.Embed(
        title="📊 RANKING SYSTEM",
        description="Earn ranks by spending time in voice channels",
        color=discord.Color.gold()
    )
    embed4.add_field(
        name="Ranks & Perks",
        value="1. **Iron** - Basic member\n"
              "2. **Bronze** - 10 hours\n"
              "3. **Silver** - 20 hours\n"
              "4. **Gold** - 30 hours + `/say`\n"
              "5. **Platinum** - 40 hours + `/say`\n"
              "6. **Diamond** - 50 hours + `/sound`\n"
              "7. **Elite** - 60 hours + `/sound`\n"
              "8. **Immortal** - 70 hours + custom sounds\n"
              "9. **Legendary** - 80 hours + custom sounds\n",
        inline=False
    )
    
    # Embed 6: Admin Manual Reset
    embed5 = discord.Embed(
        title="⚙️ MONTHLY RESET MANAGEMENT",
        description="Admin tools for voice stats reset",
        color=discord.Color.red()
    )
    embed5.add_field(
        name="⚠️ Admin Force Reset",
        value="• `/admin_force_reset` - (Admin Only) Manually trigger monthly reset immediately\n\n"
              "**What it does:**\n"
              "1️⃣ Loads previous month's archived stats\n"
              "2️⃣ Posts 'Hall of Fame' with top 3 users + elite members\n"
              "3️⃣ Resets all voice stats to 0 hours\n"
              "4️⃣ Syncs all member ranks back to Iron\n"
              "5️⃣ Updates leaderboard channels immediately\n\n"
              "📌 **Use Cases:** Testing, emergency resets, month-end adjustments",
        inline=False
    )
    embed5.set_footer(text="Type /help anytime to see this message again!")
    embeds.append(embed5)
    
    embed4.set_footer(text="")
    embeds[4] = embed4
    
    await interaction.response.send_message(embeds=embeds, ephemeral=True)


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

    # Send startup notification to each guild's main text channel
    for guild in bot.guilds:
        try:
            channel = guild.system_channel or guild.text_channels[0]
            if channel:
                await channel.send("🔄 **Beanie Bot** vừa được cập nhật và khởi động lại! Mọi tính năng đã sẵn sàng. Chúc mọi người chơi vui vẻ! 🎉")
        except Exception as e:
            logging.warning(f"Failed to send startup notification for guild {guild.id}: {e}")


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

