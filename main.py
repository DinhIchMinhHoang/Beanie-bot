# --- ALL IMPORTS AT TOP ---
import os
import subprocess
import shutil
from dotenv import load_dotenv
import logging
import time
import asyncio
import gc
import json
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from google import genai
import paramiko
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from mcstatus import JavaServer
try:
    from mcrcon import MCRcon
    RCON_PKG_AVAILABLE = True
except Exception:
    RCON_PKG_AVAILABLE = False
import pytz
from gtts import gTTS


# --- CONFIG & CONSTANTS ---
load_dotenv()
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MEMORY_LIMIT = 200
WARNING_THRESHOLD = 194
COOLDOWN_MINUTES = 60
CHUNK_SIZE = 1900

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
                    print(f"✅ Found working ffmpeg at: {path}")
                    print(f"   Version: {result.stdout.split(chr(10))[0]}")
                    return path
                else:
                    print(f"⚠️ FFmpeg at {path} returned error code {result.returncode}")
            except Exception as e:
                print(f"⚠️ FFmpeg at {path} failed to run: {e}")
    
    # If no working ffmpeg found, try to install via apt
    print("❌ No working ffmpeg found. Attempting to install via apt...")
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
            print("✅ Successfully installed ffmpeg via apt-get")
            system_ffmpeg = shutil.which("ffmpeg")
            if system_ffmpeg:
                return system_ffmpeg
    except Exception as e:
        print(f"⚠️ Could not install ffmpeg via apt: {e}")
    
    # Last resort: use system path
    print("⚠️ Using fallback: /usr/bin/ffmpeg (may not work)")
    return "/usr/bin/ffmpeg"

# Path to ffmpeg executable. If you upload a Linux ffmpeg binary to the project root,
# set FFMPEG_EXEC to './ffmpeg' or the absolute path. Can be overridden via env var.
FFMPEG_EXEC = check_and_setup_ffmpeg()

# --- Azure & SSH ENV ---
AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP")
AZURE_VM_NAME = os.getenv("AZURE_VM_NAME")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")

SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
MC_SERVER_IP = os.getenv("MC_SERVER_IP")

SHUTDOWN_MAX_WAIT = int(os.getenv("SHUTDOWN_MAX_WAIT", "300"))
SHUTDOWN_POLL_INTERVAL = int(os.getenv("SHUTDOWN_POLL_INTERVAL", "3"))
MANUAL_GRACE_MINUTES = int(os.getenv("MANUAL_GRACE_MINUTES", "10"))
MANUAL_GRACE_UNTIL = 0

# RCON settings
RCON_ENABLED = os.getenv("RCON_ENABLED", "false").lower() in ("1", "true", "yes")
RCON_HOST = os.getenv("RCON_HOST") or MC_SERVER_IP
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

AUTO_SHUTDOWN_CHANNEL_ID = int(os.getenv("AUTO_SHUTDOWN_CHANNEL_ID") or 0)
MAX_EMPTY_CHECKS = int(os.getenv("MAX_EMPTY_CHECKS", "3"))
EMPTY_CHECK_COUNT = 0
LAST_REQUEST_CHANNEL_ID = None
LAST_REQUEST_CHANNEL_FILE = "last_request_channel.txt"

# Birthday & Voice Tracking constants
BIRTHDAY_FILE = "birthdays.json"
VOICE_STATS_FILE = "voice_stats.json"
COMPETITORS_FILE = "competitors.json"
ENTRY_SETTINGS_FILE = "entry_settings.json"
STATE_FILE = "state.json"
BIRTHDAY_CHANNEL_ID = 1054049999475965972  # Voice chat text channel
RANK_CATEGORY_ID = 1472493127934677185  # Category where rank channels will be created
GENERAL_CHANNEL_ID = 1475806362393907282  # General channel for monthly reset announcements

# Azure compute client
compute_client = None
if AZURE_SUBSCRIPTION_ID and AZURE_CLIENT_ID and AZURE_CLIENT_SECRET and AZURE_TENANT_ID:
    try:
        _cred = ClientSecretCredential(
            tenant_id=AZURE_TENANT_ID,
            client_id=AZURE_CLIENT_ID,
            client_secret=AZURE_CLIENT_SECRET,
        )
        compute_client = ComputeManagementClient(_cred, AZURE_SUBSCRIPTION_ID)
    except Exception as e:
        logging.warning(f"Azure client init failed: {e}")

# --- External Service Setup ---
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

GUILD_ID = int(os.getenv("GUILD_ID") or 0)
# Rank role ids (from spec)
RANK_ROLE_IDS = [
    1475819335514849391, # Iron
    1475808729705353290, # Bronze
    1475808847649181778, # Silver
    1475808898370769018, # Gold
    1475809119049875528, # Platinum
    1475808953681051738, # Diamond
    1475813832411709461, # Elite
    1475813978201653330, # Immortal
    1475814299120435301, # Legendary
]

# --- Shared State (minimal RAM usage) ---
chat_memory = []
lockdown = False
lockdown_until = None
voice_join_times = {}  # {user_id: start_timestamp} - only in RAM
last_birthday_check = None  # Track last birthday check date to run once per day

# --- Audio Infrastructure (Traffic Control) ---
audio_lock = asyncio.Lock()
say_queue = asyncio.Queue(maxsize=10)
say_cooldowns = {}  # {user_id: timestamp}

# Birthday wishes (10+ diverse messages)
BIRTHDAY_WISHES = [
    "🎉 Chúc mừng sinh nhật {name}! Tuổi mới vạn sự như ý, tiền vào như nước! 💰🎂",
    "🎂 Happy Birthday {name}! Chúc bạn luôn vui vẻ, hạnh phúc và... không bao giờ già! 😎🎈",
    "🥳 Sinh nhật vui vẻ {name}! Một tuổi mới thêm xinh đẹp, thêm giàu, thêm... béo? 😂🍰",
    "🎊 {name} ơi, sinh nhật zui zẻ nha! Chúc bạn luôn 'dope' và 'swag' như mọi khi! 🔥🎁",
    "🎉 Chúc mừng sinh nhật {name}! Tuổi mới học giỏi, chơi khỏe, ăn ngon, ngủ sâu! 🌟🎂",
    "🎈 Happy Birthday to you {name}! May your day be as awesome as your memes! 🎮🎉",
    "🎂 {name} thêm một tuổi mới! Chúc bạn 'level up' thành công trong cuộc sống real! 🚀✨",
    "🥳 Sinh nhật vui vẻ {name}! Chúc bạn luôn tươi trẻ, năng động và không bao giờ hết pin! 🔋😄",
    "🎊 {name} ơi! Chúc mừng sinh nhật! Năm nay phải giàu hơn năm ngoái nha! 💎🎁",
    "🎉 Happy Birthday {name}! Chúc tuổi mới nhiều niềm vui, ít drama, full happiness! 🌈🎂",
    "🎂 Sinh nhật zui zẻ {name}! Chúc bạn luôn 'on top' và không bao giờ 'flop'! 🎯🔥",
    "🥳 {name} thêm tuổi rồi nè! Chúc ngày càng xinh/đẹp, giàu có và hạnh phúc! 💖🎈"
]

def get_context():
    return [f"{m['user']}: {m['content']}" for m in chat_memory]

# --- Logging Setup (with auto-trim) ---
class MemoryLimitFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        try:
            with open(self.baseFilename, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MEMORY_LIMIT:
                lines = lines[-MEMORY_LIMIT:]
                with open(self.baseFilename, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        MemoryLimitFileHandler("beanie.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# --- LAZY LOADING HELPERS (NO GLOBAL JSON DATA) ---

def load_birthdays():
    """Lazy load birthdays from JSON file. Returns dict."""
    if not os.path.exists(BIRTHDAY_FILE):
        return {}
    try:
        with open(BIRTHDAY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_birthdays(data):
    """Save birthdays to JSON file."""
    try:
        with open(BIRTHDAY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save birthdays: {e}")

def load_voice_stats():
    """Lazy load voice stats from JSON file. Returns dict {user_id: total_seconds}.
    Auto-migrates old format to new format.
    """
    if not os.path.exists(VOICE_STATS_FILE):
        logging.info(f"voice stats file not found: {VOICE_STATS_FILE}")
        return {}
    try:
        size = os.path.getsize(VOICE_STATS_FILE)
        logging.info(f"Loading voice stats from {VOICE_STATS_FILE} (size={size} bytes)")
    except Exception as e:
        logging.warning(f"Could not stat {VOICE_STATS_FILE}: {e}")
    try:
        # Use utf-8-sig to gracefully handle files that include a BOM
        with open(VOICE_STATS_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"Failed to load {VOICE_STATS_FILE}: {e}")
        try:
            # try to read raw content for debugging
            with open(VOICE_STATS_FILE, "r", encoding="utf-8", errors='replace') as f:
                raw = f.read(1000)
            logging.error(f"Raw start of {VOICE_STATS_FILE}: {raw!r}")
        except Exception:
            logging.error("Also failed to read raw content of voice_stats.json")
        return {}

    # Auto-migrate old format to new format
    migrated = {}
    try:
        for user_id, value in data.items():
            if isinstance(value, dict) and "total" in value:
                # Old format: {"months": {...}, "total": 123}
                migrated[user_id] = value["total"]
            elif isinstance(value, (int, float)):
                # New format: just the number
                migrated[user_id] = value
            else:
                migrated[user_id] = 0
    except Exception as e:
        logging.error(f"Error migrating voice stats structure: {e}")
        return {}
    return migrated

def save_voice_stats(data):
    """Save voice stats to JSON file."""
    try:
        tmp = VOICE_STATS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, VOICE_STATS_FILE)
    except Exception as e:
        logging.error(f"Failed to save voice stats atomically: {e}")


def load_all_time_stats():
    """Load cumulative voice stats across current stats file and all monthly archive files.
    Returns a dict {user_id: total_seconds} aggregated across archives and current file.
    """
    totals = {}
    # Start with current stats
    try:
        current = load_voice_stats()
        for uid, secs in current.items():
            totals[uid] = totals.get(uid, 0) + int(secs or 0)
    except Exception as e:
        logging.warning(f"Failed to load current voice stats for all-time aggregation: {e}")

    # Then include any archive_YYYY_MM.json files
    try:
        for fname in os.listdir('.'):
            if fname.startswith('archive_') and fname.endswith('.json'):
                try:
                    with open(fname, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                    for uid, secs in data.items():
                        totals[uid] = totals.get(uid, 0) + int(secs or 0)
                except Exception as e:
                    logging.warning(f"Failed to include archive file {fname}: {e}")
    except Exception as e:
        logging.warning(f"Failed to scan archive files for all-time stats: {e}")

    return totals

def load_competitors():
    """Lazy load competitors dict from JSON file. Returns dict {user_id: channel_id}."""
    if not os.path.exists(COMPETITORS_FILE):
        return {}
    try:
        with open(COMPETITORS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Handle migration from list to dict
            if isinstance(data, list):
                return {str(uid): None for uid in data}
            return data
    except Exception:
        return {}

def save_competitors(data):
    """Save competitors dict to JSON file."""
    try:
        with open(COMPETITORS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save competitors: {e}")

def load_entry_settings():
    """Lazy load entry settings from JSON file. Returns dict {user_id: {enabled: bool, type: str, text: str}}."""
    if not os.path.exists(ENTRY_SETTINGS_FILE):
        return {}
    try:
        with open(ENTRY_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_entry_settings(data):
    """Save entry settings to JSON file."""
    try:
        with open(ENTRY_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save entry settings: {e}")

def load_state():
    """Lazy load state from JSON file. Returns dict."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(data):
    """Save state to JSON file."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save state: {e}")

def get_user_rank(total_hours):
    """Get rank name, perks, and role ID based on total hours.
    
    Returns: (rank_name, role_id, perks_list)
    """
    if total_hours >= 80:
        return ("Legendary", 1475814299120435301, ["/say", "/entry on/off", "/entry add - Custom TTS/File"])
    elif total_hours >= 70:
        return ("Immortal", 1475813978201653330, ["/say", "/entry on/off", "/entry add - Custom TTS/File"])
    elif total_hours >= 60:
        return ("Elite", 1475813832411709461, ["/say", "/entry on/off", 'Default Entrance: "Xin chào {name}"'])
    elif total_hours >= 50:
        return ("Diamond", 1475808953681051738, ["/say", "/entry on/off", 'Default Entrance: "Xin chào {name}"'])
    elif total_hours >= 40:
        return ("Platinum", 1475809119049875528, ["/say"])
    elif total_hours >= 30:
        return ("Gold", 1475808898370769018, ["/say"])
    elif total_hours >= 20:
        return ("Silver", 1475808847649181778, [])
    elif total_hours >= 10:
        return ("Bronze", 1475808729705353290, [])
    else:
        return ("Iron", 1475819335514849391, [])

def add_to_memory(user, content):
    global chat_memory
    now_vn = datetime.now(VIETNAM_TZ)
    chat_memory.append({"user": user, "content": content, "time": now_vn})
    if len(chat_memory) > MEMORY_LIMIT:
        chat_memory.pop(0)
    
    # Save chat history to file (auto-trim)
    try:
        if os.path.exists("chat_history.txt"):
            with open("chat_history.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        lines.append(f"[{datetime.now(pytz.UTC).isoformat()}] {user}: {content}\n")
        if len(lines) > MEMORY_LIMIT:
            lines = lines[-MEMORY_LIMIT:]
        with open("chat_history.txt", "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        logging.error(f"Failed to write chat history: {e}")

# --- Azure & SSH Helpers ---

def azure_start_vm():
    if not compute_client:
        raise RuntimeError("Azure not configured")
    async_action = compute_client.virtual_machines.begin_start(AZURE_RESOURCE_GROUP, AZURE_VM_NAME)
    async_action.wait()

def azure_stop_vm():
    if not compute_client:
        raise RuntimeError("Azure not configured")
    async_action = compute_client.virtual_machines.begin_deallocate(AZURE_RESOURCE_GROUP, AZURE_VM_NAME)
    async_action.wait()

def vm_is_running():
    if not compute_client:
        return False
    try:
        vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
        return "running" in vm.instance_view.statuses[1].display_status.lower()
    except Exception:
        return False

def ssh_command(command, timeout=10):
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if not SSH_PASSWORD:
            return "SSH disabled: no SSH_PASSWORD configured"
        c.connect(hostname=SSH_HOST, username=SSH_USER, password=SSH_PASSWORD, timeout=timeout)
        stdin, stdout, stderr = c.exec_command(command)
        output = stdout.read().decode(errors='ignore')
        err = stderr.read().decode(errors='ignore')
        c.close()
        if err:
            return output + "\nERR:\n" + err
        return output
    except Exception as e:
        return str(e)

def wait_for_mc_shutdown(max_wait=SHUTDOWN_MAX_WAIT, poll_interval=SHUTDOWN_POLL_INTERVAL):
    start = time.time()
    if SSH_PASSWORD and SSH_HOST and SSH_USER:
        while time.time() - start < max_wait:
            try:
                cmd = 'bash -lc "screen -ls | grep mc >/dev/null && echo RUNNING || echo STOPPED"'
                out = ssh_command(cmd, timeout=5)
                if isinstance(out, str) and out.strip().startswith("STOPPED"):
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False

    if MC_SERVER_IP:
        while time.time() - start < max_wait:
            try:
                server = JavaServer.lookup(MC_SERVER_IP)
                _ = server.status()
            except Exception:
                return True
            time.sleep(poll_interval)
        return False

    return False

def rcon_command(command, timeout=10):
    if not RCON_PKG_AVAILABLE:
        raise RuntimeError("mcrcon package not installed")
    if not RCON_ENABLED:
        raise RuntimeError("RCON not enabled in env")
    if not RCON_PASSWORD:
        raise RuntimeError("RCON password not configured")
    host = RCON_HOST or MC_SERVER_IP
    try:
        with MCRcon(host, RCON_PASSWORD, port=RCON_PORT) as mcr:
            out = mcr.command(command)
            return out
    except Exception:
        raise

def get_current_player_count():
    try:
        if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD and vm_is_running():
            try:
                out = rcon_command('list')
                import re
                m = re.search(r"There are (\d+) of a max", out)
                if m:
                    return int(m.group(1))
                return 0
            except Exception:
                pass
        if MC_SERVER_IP:
            try:
                server = JavaServer.lookup(MC_SERVER_IP)
                status_mc = server.status()
                return int(status_mc.players.online)
            except Exception:
                pass
        if SSH_PASSWORD and SSH_HOST and SSH_USER:
            try:
                cmd = 'bash -lc "screen -ls | grep mc >/dev/null && echo RUNNING || echo STOPPED"'
                out = ssh_command(cmd, timeout=5)
                if isinstance(out, str) and out.strip().startswith("RUNNING"):
                    return 1
                return 0
            except Exception:
                pass
    except Exception:
        return None
    return None

async def async_get_player_count(timeout=5):
    try:
        if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD and vm_is_running():
            try:
                out = await asyncio.wait_for(asyncio.to_thread(rcon_command, 'list'), timeout=timeout)
                import re
                m = re.search(r"There are (\d+) of a max", out)
                if m:
                    return int(m.group(1))
                return 0
            except Exception:
                pass
        if MC_SERVER_IP:
            try:
                status_mc = await asyncio.wait_for(asyncio.to_thread(lambda: JavaServer.lookup(MC_SERVER_IP).status()), timeout=timeout)
                return int(status_mc.players.online)
            except Exception:
                pass
        if SSH_PASSWORD and SSH_HOST and SSH_USER:
            try:
                cmd = 'bash -lc "screen -ls | grep mc >/dev/null && echo RUNNING || echo STOPPED"'
                out = await asyncio.wait_for(asyncio.to_thread(ssh_command, cmd, 5), timeout=timeout)
                if isinstance(out, str) and out.strip().startswith("RUNNING"):
                    return 1
                return 0
            except Exception:
                pass
    except Exception:
        return None
    return None

def clear_memory():
    global chat_memory
    chat_memory = []
    gc.collect()


async def apply_rank_roles_to_guild(guild: discord.Guild):
    """Apply rank roles to all members in a guild based on voice_stats.json.
    Adds the correct rank role and removes other rank roles.
    Requires Manage Roles permission and bot role high enough.
    """
    stats = load_voice_stats()
    competitors = load_competitors()
    competitors_set = set(competitors.keys())
    # preload role objects
    role_map = {rid: guild.get_role(rid) for rid in RANK_ROLE_IDS}

    for member in guild.members:
        try:
            user_id = str(member.id)

            # find any current rank roles the member has
            current_rank_roles = [r for r in member.roles if r.id in RANK_ROLE_IDS]

            # If the member is NOT in competitors, remove any rank roles and continue
            if user_id not in competitors_set:
                if current_rank_roles:
                    try:
                        await member.remove_roles(*current_rank_roles, reason="Rank sync: not a competitor")
                        logging.info(f"Removed rank roles from non-competitor {member.display_name} ({member.id})")
                    except Exception as e:
                        logging.warning(f"Failed to remove roles for {member.id}: {e}")
                continue

            # Member is a competitor -> compute target rank
            total_seconds = stats.get(user_id, 0)
            total_hours = total_seconds / 3600
            rank_name, role_id, _ = get_user_rank(total_hours)

            target_role = role_map.get(role_id)
            if target_role is None:
                logging.warning(f"Role id {role_id} not found in guild {guild.id}")
                continue

            # If member already has target role, ensure no other rank roles
            if any(r.id == role_id for r in current_rank_roles):
                to_remove = [r for r in current_rank_roles if r.id != role_id]
                if to_remove:
                    try:
                        await member.remove_roles(*to_remove, reason="Rank sync: remove extras")
                        logging.info(f"Removed extra rank roles from {member.display_name} ({member.id})")
                    except Exception as e:
                        logging.warning(f"Failed to remove roles for {member.id}: {e}")
                continue

            # Add target role
            try:
                await member.add_roles(target_role, reason="Rank sync: assigned role")
                logging.info(f"Assigned role {target_role.id} to {member.display_name} ({member.id})")
            except Exception as e:
                logging.warning(f"Failed to add role {role_id} to {member.id}: {e}")

            # remove any other rank roles
            to_remove = [r for r in current_rank_roles if r.id != role_id]
            if to_remove:
                try:
                    await member.remove_roles(*to_remove, reason="Rank sync: remove old roles")
                except Exception as e:
                    logging.warning(f"Failed to remove old rank roles for {member.id}: {e}")

            # small sleep to avoid rate limits
            await asyncio.sleep(0.15)

        except Exception as e:
            logging.error(f"Error applying rank for member {member.id}: {e}")


@tree.command(name="sync_roles", description="(Admin) Sync rank roles for the guild now")
async def sync_roles_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ Guild context required.", ephemeral=True)
        return
    try:
        await apply_rank_roles_to_guild(guild)
        await interaction.followup.send("✅ Role sync completed.", ephemeral=True)
    except Exception as e:
        logging.error(f"Manual role sync failed: {e}")
        await interaction.followup.send(f"❌ Role sync failed: {e}", ephemeral=True)


@tasks.loop(hours=1)
async def periodic_role_sync():
    await bot.wait_until_ready()
    try:
        for guild in bot.guilds:
            await apply_rank_roles_to_guild(guild)
    except Exception as e:
        logging.error(f"Periodic role sync error: {e}")

def check_lockdown():
    global lockdown, lockdown_until
    now_vn = datetime.now(VIETNAM_TZ)
    if lockdown and lockdown_until and now_vn >= lockdown_until:
        lockdown = False
        lockdown_until = None
        clear_memory()
        return True
    return False

def checkpoint_voice_stats():
    """Checkpoint voice stats for users currently in voice channels.
    Updates their total time and resets their join timestamp.
    """
    now = time.time()
    if not voice_join_times:
        return
    
    stats = load_voice_stats()
    for user_id, join_time in list(voice_join_times.items()):
        duration = now - join_time
        if user_id not in stats:
            stats[user_id] = 0
        stats[user_id] += duration
        voice_join_times[user_id] = now  # Reset to current time
    
    save_voice_stats(stats)
    gc.collect()

# --- BACKGROUND TASKS ---

@tasks.loop(minutes=1)
async def cooldown_check():
    if check_lockdown():
        for guild in bot.guilds:
            for channel in guild.text_channels:
                try:
                    await channel.send("🔔 AI Chat is available now!")
                except:
                    continue

@tasks.loop(minutes=1)
async def birthday_check():
    """Check birthdays at midnight (00:00) Hanoi time and send wishes."""
    global last_birthday_check
    await bot.wait_until_ready()
    now = datetime.now(VIETNAM_TZ)
    today = now.date()
    
    # Only run once per day at exactly 00:00
    if now.hour != 0 or now.minute != 0 or last_birthday_check == today:
        return
    
    last_birthday_check = today
    today_str = now.strftime("%d/%m")
    birthdays = load_birthdays()
    
    # Find birthdays today
    for user_id, date_str in birthdays.items():
        if date_str == today_str:
            # Send birthday wish
            channel = bot.get_channel(BIRTHDAY_CHANNEL_ID)
            if channel:
                try:
                    member = await bot.fetch_user(int(user_id))
                    name = member.display_name if member else f"<@{user_id}>"
                    import random
                    wish = random.choice(BIRTHDAY_WISHES).format(name=name)
                    await channel.send(wish)
                except Exception as e:
                    logging.error(f"Failed to send birthday wish: {e}")
    
    gc.collect()

@tasks.loop(hours=1)
async def update_leaderboard():
    """Update voice channel names hourly with all competitors (including those currently in voice)."""
    await bot.wait_until_ready()
    
    competitors = load_competitors()
    if not competitors:
        return
    
    # Checkpoint: Save current voice stats for people in voice channels
    checkpoint_voice_stats()
    
    # Get updated stats after checkpoint
    stats = load_voice_stats()
    logging.info(f"Leaderboard update - loaded stats sample: {dict(list(stats.items())[:10])}")
    
    # Get all-time totals for competitors
    rankings = []
    for user_id_str, channel_id in competitors.items():
        user_id = str(user_id_str)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rankings.append((int(user_id), total_hours, channel_id))
    
    # Sort by hours descending
    rankings.sort(key=lambda x: x[1], reverse=True)
    
    # Update channels with name AND position for proper sorting
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, hours, channel_id) in enumerate(rankings):
        if not channel_id:
            continue
        try:
            logging.info(f"Updating channel {channel_id} for user {user_id} -> {hours:.2f}h")
            channel = bot.get_channel(int(channel_id))
            if not channel:
                continue
            
            try:
                member = await bot.fetch_user(user_id)
                name = member.display_name if member else f"User{user_id}"
            except:
                name = f"User{user_id}"
            
            if i < len(medals):
                medal = medals[i]
            else:
                medal = f"#{i+1}"
            new_name = f"{medal} {name}: {int(hours)}h"
            
            # Update both name and position to sort channels correctly
            await channel.edit(name=new_name, position=i)
            
            # Discord rate limit: 2 channel edits per 10 seconds
            # Wait 5 seconds between edits to stay compliant
            if i < len(rankings) - 1:  # Don't wait after last channel
                await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"Failed to update leaderboard channel {channel_id}: {e}")
    
    gc.collect()

@tasks.loop(minutes=5)
async def auto_shutdown_check():
    global EMPTY_CHECK_COUNT
    try:
        if not compute_client:
            return
        vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
        if "running" not in vm.instance_view.statuses[1].display_status.lower():
            EMPTY_CHECK_COUNT = 0
            try:
                auto_shutdown_check.stop()
            except Exception:
                pass
            return

        try:
            if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
                try:
                    out = await asyncio.wait_for(asyncio.to_thread(rcon_command, 'list'), timeout=5)
                    import re
                    m = re.search(r"There are (\d+) of a max", out)
                    if m:
                        players = int(m.group(1))
                    else:
                        players = 0
                except Exception:
                    players = 0
            else:
                server = JavaServer.lookup(MC_SERVER_IP)
                status_mc = server.status()
                players = status_mc.players.online
        except Exception:
            players = 0

        if players == 0:
            EMPTY_CHECK_COUNT += 1
        else:
            EMPTY_CHECK_COUNT = 0

        if EMPTY_CHECK_COUNT >= MAX_EMPTY_CHECKS:
            channel = None
            try:
                if LAST_REQUEST_CHANNEL_ID:
                    channel = bot.get_channel(LAST_REQUEST_CHANNEL_ID)
            except Exception:
                channel = None
            if not channel and AUTO_SHUTDOWN_CHANNEL_ID:
                channel = bot.get_channel(AUTO_SHUTDOWN_CHANNEL_ID)
            
            if MANUAL_GRACE_UNTIL and time.time() < MANUAL_GRACE_UNTIL:
                EMPTY_CHECK_COUNT = 0
                return
            
            if MC_SERVER_IP:
                try:
                    status_mc = await asyncio.wait_for(asyncio.to_thread(lambda: JavaServer.lookup(MC_SERVER_IP).status()), timeout=5)
                except Exception:
                    if channel:
                        await channel.send("⚠️ Không thể track được mcstatus - hủy auto-shutdown.")
                    EMPTY_CHECK_COUNT = 0
                    return
                players_now = int(status_mc.players.online)
                if players_now > 0:
                    EMPTY_CHECK_COUNT = 0
                    return
                if channel:
                    await channel.send("⚠️ Không có ai chơi trong thời gian dài, Bot sẽ tắt máy để tiết kiệm chi phí.")
            else:
                EMPTY_CHECK_COUNT = 0
                return
            
            await asyncio.to_thread(ssh_command, 'screen -S mc -p 0 -X stuff "stop^M"')
            try:
                confirmed = await asyncio.to_thread(wait_for_mc_shutdown, 45, 5)
            except Exception:
                confirmed = False

            if not confirmed:
                if channel:
                    await channel.send("⚠️ Auto-Shutdown: Server bị treo (Freeze). Thực hiện Force Kill...")
                await asyncio.to_thread(ssh_command, 'pkill -9 -f java')
                await asyncio.sleep(5)
                confirmed = await asyncio.to_thread(wait_for_mc_shutdown, 10, 2)

            if confirmed:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, azure_stop_vm)
                if channel:
                    await channel.send("💤 Đã tự động tắt máy thành công!")
            else:
                if channel:
                    await channel.send("⚠️ Bot không thể xác nhận Minecraft đã tắt (kể cả sau khi Force Kill); VM sẽ KHÔNG tắt. Vui lòng kiểm tra.")
            
            EMPTY_CHECK_COUNT = 0

    except Exception as e:
        logging.warning(f"auto_shutdown_check error: {e}")

@tasks.loop(minutes=5)
async def monthly_reset_check():
    """Check if we need to reset voice stats at the start of a new month."""
    await bot.wait_until_ready()
    
    now = datetime.now(VIETNAM_TZ)
    state = load_state()
    last_reset_month = state.get("last_reset_month")

    # Check current month
    current_month = now.month

    # If we have no recorded last reset month, initialize it and skip reset
    if last_reset_month is None:
        state["last_reset_month"] = current_month
        save_state(state)
        return

    # If already recorded for this month, nothing to do
    if last_reset_month == current_month:
        return

    # It's a new month (and we had a previous month recorded) -> perform reset
    logging.info(f"Monthly reset triggered for month {current_month} (last: {last_reset_month})")
    
    # 1. Checkpoint current stats first
    checkpoint_voice_stats()
    
    # 2. Load final stats before reset
    stats = load_voice_stats()
    
    # 3. Find Top 3 and Immortal/Legendary users
    rankings = []
    for user_id, total_seconds in stats.items():
        total_hours = total_seconds / 3600
        rank_name, role_id, perks = get_user_rank(total_hours)
        rankings.append((int(user_id), total_hours, rank_name))
    
    rankings.sort(key=lambda x: x[1], reverse=True)
    
    # 4. Prepare Hall of Fame message
    channel = bot.get_channel(GENERAL_CHANNEL_ID)
    if channel and rankings:
        embed = discord.Embed(
            title="🏆 HỘI ĐƯỜNG DANH VỌNG - THÁNG QUA 🏆",
            description=f"Chúc mừng những chiến binh đã cống hiến thời gian cho server!",
            color=discord.Color.gold()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        top_3 = rankings[:3]
        
        for i, (user_id, hours, rank_name) in enumerate(top_3):
            try:
                member = await bot.fetch_user(user_id)
                name = member.display_name if member else f"<@{user_id}>"
            except:
                name = f"<@{user_id}>"
            
            medal = medals[i]
            embed.add_field(
                name=f"{medal} {name}",
                value=f"**{int(hours)}h {int((hours % 1) * 60)}m** - Rank: {rank_name}",
                inline=False
            )
        
        # List Immortal/Legendary users
        elite_users = [r for r in rankings if r[2] in ["Immortal", "Legendary"]]
        if elite_users:
            elite_lines = []
            for uid, hrs, rank in elite_users:
                try:
                    user = await bot.fetch_user(uid)
                    display = user.display_name if user else f'<@{uid}>'
                except Exception:
                    display = f'<@{uid}>'
                elite_lines.append(f"⭐ {display}: **{rank}**")
            elite_text = "\n".join(elite_lines)
            embed.add_field(
                name="💎 Immortal & Legendary Warriors",
                value=elite_text[:1024],
                inline=False
            )
        
        embed.set_footer(text=f"Stats reset vào {now.strftime('%d/%m/%Y %H:%M')} (Giờ Việt Nam)")
        
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logging.error(f"Failed to send Hall of Fame: {e}")
    
    # 5. Backup stats to archive file
    archive_filename = f"archive_{now.year}_{str(now.month).zfill(2)}.json"
    try:
        with open(archive_filename, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        logging.info(f"Archived stats to {archive_filename}")
    except Exception as e:
        logging.error(f"Failed to archive stats: {e}")
    
    # 6. Reset all stats to 0
    reset_stats = {user_id: 0 for user_id in stats.keys()}
    save_voice_stats(reset_stats)
    logging.info("Voice stats reset to 0 for all users")
    
    # 7. Sync roles to match new stats (everyone back to Iron)
    try:
        for guild in bot.guilds:
            await apply_rank_roles_to_guild(guild)
            await asyncio.sleep(1)  # Small delay between guilds
        logging.info("Monthly reset: roles synced across all guilds")
    except Exception as e:
        logging.error(f"Failed to sync roles after monthly reset: {e}")
    
    # 8. Update state
    state["last_reset_month"] = current_month
    save_state(state)
    
    gc.collect()

# --- EVENTS ---

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    # Create sfx directory if it doesn't exist
    os.makedirs("sfx", exist_ok=True)
    
    # Cleanup orphaned TTS files from previous sessions
    try:
        for filename in os.listdir("sfx"):
            if filename.startswith("tts_"):
                file_path = os.path.join("sfx", filename)
                try:
                    os.remove(file_path)
                    logging.info(f"Cleaned up orphaned file: {filename}")
                except Exception as e:
                    logging.warning(f"Failed to delete {filename}: {e}")
    except Exception as e:
        logging.warning(f"Failed to cleanup sfx folder: {e}")
    
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            try:
                await tree.copy_global_to(guild=guild_obj)
            except Exception:
                pass
            synced = await tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}.")
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
    
    cooldown_check.start()
    birthday_check.start()
    update_leaderboard.start()
    monthly_reset_check.start()
    
    # Start say queue processor
    asyncio.create_task(process_say_queue())
    
    # Start periodic role sync
    try:
        periodic_role_sync.start()
    except RuntimeError:
        pass
    
    try:
        auto_shutdown_check.start()
    except RuntimeError:
        pass

    global LAST_REQUEST_CHANNEL_ID
    try:
        if os.path.exists(LAST_REQUEST_CHANNEL_FILE):
            with open(LAST_REQUEST_CHANNEL_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    LAST_REQUEST_CHANNEL_ID = int(val)
    except Exception as e:
        logging.warning(f"Could not load last request channel: {e}")

async def process_say_queue():
    """Background task to process /say commands from the queue."""
    while True:
        try:
            # Wait for next item in queue
            interaction, message_text = await say_queue.get()
            
            # Get user's voice channel
            if not interaction.user.voice or not interaction.user.voice.channel:
                try:
                    await interaction.followup.send("❌ Bạn phải ở trong voice channel!", ephemeral=True)
                except:
                    pass
                continue
            
            voice_channel = interaction.user.voice.channel
            
            # Generate TTS file
            temp_file = f"sfx/tts_{interaction.id}.mp3"
            try:
                tts = gTTS(text=message_text, lang='vi', slow=False)
                await asyncio.to_thread(tts.save, temp_file)
            except Exception as e:
                try:
                    await interaction.followup.send(f"❌ TTS generation failed: {e}", ephemeral=True)
                except:
                    pass
                continue
            
            # Acquire audio lock and play
            async with audio_lock:
                try:
                    # Connect to voice
                    voice_client = None
                    for vc in bot.voice_clients:
                        if vc.guild.id == interaction.guild.id:
                            voice_client = vc
                            break
                    
                    if not voice_client or not voice_client.is_connected():
                        voice_client = await voice_channel.connect()
                    elif voice_client.channel.id != voice_channel.id:
                        await voice_client.move_to(voice_channel)
                    
                    # Play audio
                    voice_client.play(discord.FFmpegPCMAudio(temp_file, executable=FFMPEG_EXEC))
                    
                    # Wait for playback to finish
                    while voice_client.is_playing():
                        await asyncio.sleep(0.1)
                    
                    # Disconnect
                    await voice_client.disconnect()
                    
                except Exception as e:
                    logging.error(f"Say playback error: {e}")
                    try:
                        await interaction.followup.send(f"❌ Playback failed: {e}", ephemeral=True)
                    except:
                        pass
                finally:
                    # Always delete the temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except Exception as e:
                        logging.warning(f"Failed to delete temp file {temp_file}: {e}")
                    gc.collect()
        
        except Exception as e:
            logging.error(f"Say queue processor error: {e}")
            await asyncio.sleep(1)

@bot.event
async def on_voice_state_update(member, before, after):
    """Track admin voice time and handle entrance sounds for Diamond+ users."""
    # Only track admins
    if not member.guild_permissions.administrator:
        return
    
    user_id = str(member.id)
    now = time.time()
    
    # Joined voice channel
    if before.channel is None and after.channel is not None:
        voice_join_times[user_id] = now
        
        # Check rank for entrance sound (Diamond+)
        stats = load_voice_stats()
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks = get_user_rank(total_hours)
        logging.info(f"Voice join detected: {member.display_name} ({member.id}) rank={rank_name} hours={total_hours:.2f}")

        # Diamond+ ranks can have entrance sounds
        if rank_name in ["Diamond", "Elite", "Immortal", "Legendary"]:
            entry_settings = load_entry_settings()
            user_settings = entry_settings.get(user_id, {"enabled": True, "type": "default"})
            logging.info(f"Entry settings for {member.display_name} ({member.id}): {user_settings}")
            
            # Check if entrance is enabled
            if user_settings.get("enabled", True):
                # If audio is already playing, drop the entrance sound
                if audio_lock.locked():
                    logging.info(f"Dropped entrance sound for {member.display_name} - audio lock busy")
                    return
                logging.info(f"Scheduling entrance sound for {member.display_name} ({member.id})")
                # Play entrance sound
                asyncio.create_task(play_entrance_sound(member, after.channel, rank_name, user_settings))
    
    # Left voice channel
    elif before.channel is not None and after.channel is None:
        if user_id in voice_join_times:
            start_time = voice_join_times.pop(user_id)
            duration = now - start_time
            
            # Immediately save to JSON (persistence!)
            stats = load_voice_stats()
            if user_id not in stats:
                stats[user_id] = 0
            
            stats[user_id] += duration
            
            save_voice_stats(stats)
            gc.collect()

async def play_entrance_sound(member, voice_channel, rank_name, user_settings):
    """Play entrance sound for a user joining voice channel."""
    try:
        async with audio_lock:
            user_id = str(member.id)
            entry_type = user_settings.get("type", "default")
            
            # For Immortal/Legendary with custom setup, play custom sound
            if rank_name in ["Immortal", "Legendary"] and entry_type in ["tts", "file"]:
                # Look for custom file
                custom_files = [f"sfx/custom_{user_id}.mp3", f"sfx/custom_{user_id}.ogg"]
                audio_file = None
                for cf in custom_files:
                    if os.path.exists(cf):
                        audio_file = cf
                        break
                
                if audio_file:
                    # Play custom file
                    try:
                        logging.info(f"Found custom entrance file for {member.display_name} ({member.id}): {audio_file}")
                        voice_client = None
                        # Find existing voice client for this guild from bot.voice_clients
                        for vc in bot.voice_clients:
                            if vc.guild.id == member.guild.id and vc.channel.id == voice_channel.id:
                                voice_client = vc
                                break
                        
                        if not voice_client:
                            voice_client = await voice_channel.connect()
                        
                        voice_client.play(discord.FFmpegPCMAudio(audio_file, executable=FFMPEG_EXEC))
                        
                        # Wait for playback to finish
                        while voice_client.is_playing():
                            await asyncio.sleep(0.1)
                        
                        await voice_client.disconnect()
                        return
                    except Exception as e:
                        logging.error(f"Failed to play custom entrance for {member.display_name}: {e}")
            
            # Default: Generate TTS "Xin chào {name}" for Diamond/Elite or fallback
            if rank_name in ["Diamond", "Elite", "Immortal", "Legendary"]:
                temp_file = f"sfx/tts_entrance_{member.id}.mp3"
                try:
                    message = f"Xin chào {member.display_name}"
                    logging.info(f"Generating TTS entrance for {member.display_name} ({member.id}): '{message}'")
                    tts = gTTS(text=message, lang='vi', slow=False)
                    await asyncio.to_thread(tts.save, temp_file)
                    
                    # Play TTS
                    voice_client = None
                    for vc in bot.voice_clients:
                        if vc.guild.id == member.guild.id and vc.channel.id == voice_channel.id:
                            voice_client = vc
                            break
                    
                    if not voice_client:
                        voice_client = await voice_channel.connect()
                    
                    voice_client.play(discord.FFmpegPCMAudio(temp_file, executable=FFMPEG_EXEC))
                    
                    # Wait for playback to finish
                    while voice_client.is_playing():
                        await asyncio.sleep(0.1)
                    
                    await voice_client.disconnect()
                    
                except Exception as e:
                    logging.error(f"Failed to play default entrance TTS for {member.display_name}: {e}")
                finally:
                    # Delete temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass
                    gc.collect()
    
    except Exception as e:
        logging.error(f"Entrance sound error for {member.display_name}: {e}")

# --- AI Queue Processing ---
ai_queue = asyncio.Queue()
ai_processing = False

@bot.event
async def on_message(message):
    global lockdown, lockdown_until, ai_processing
    if message.author.bot:
        return
    if not message.content.lower().startswith("/beanie"):
        return
    if lockdown:
        await message.reply("⏳ AI Chat is cooling down. Please wait.")
        return
    text = message.content[len("/beanie"):].strip()
    if not text:
        await message.reply("Please type something after /beanie!")
        return
    await ai_queue.put((message, text))
    if not ai_processing:
        asyncio.create_task(process_ai_queue())

async def process_ai_queue():
    global ai_processing, lockdown, lockdown_until
    ai_processing = True
    while not ai_queue.empty():
        message, text = await ai_queue.get()
        add_to_memory(message.author.display_name, text)

        if len(chat_memory) == WARNING_THRESHOLD:
            await message.channel.send("⚠️ You have 3 messages left, make them worthy!")
        if len(chat_memory) >= MEMORY_LIMIT:
            lockdown = True
            now_vn = datetime.now(VIETNAM_TZ)
            lockdown_until = now_vn + timedelta(minutes=COOLDOWN_MINUTES)
            await message.channel.send("🔒 AI Chat is now locked for 1 hour! (Vietnam time)")
            continue

        async with message.channel.typing():
            system_prompt = (
                "Bạn là Beanie, một thanh niên Việt Nam chất chơi, hài hước, lém lỉnh, biết trêu chọc, khen ngợi, và luôn làm theo yêu cầu của người dùng. "
                "Hãy trả lời như một người bạn thân, có thể pha trò, chọc nhẹ, khen ngợi, hoặc 'assault' vui vẻ nhưng không xúc phạm. Trả lời ngắn gọn và dứt khoát. Đừng bắt đầu câu trả lời với 'Ulatr!' hoặc bất kỳ từ cảm thán nào quá thường xuyên. Hãy đa dạng cách diễn đạt và chỉ dùng icon hoặc biểu tượng khi thật sự phù hợp, không phải lúc nào cũng cần."
                "Luôn giữ sự hài hước, dí dỏm, và phong cách 'dope' của giới trẻ Việt Nam. "
                "Nếu người dùng hỏi bằng tiếng Anh, hãy trả lời bằng tiếng Anh với phong cách tương tự. Nếu hỏi bằng tiếng Việt, hãy trả lời bằng tiếng Việt. "
                "Nếu không chắc ngôn ngữ, hãy ưu tiên tiếng Việt. Không được trả lời quá lịch sự hoặc quá máy móc."
            )
            context = get_context()
            prompt = system_prompt + "\n" + "\n".join(context[-20:]) + f"\nBeanie:"

            try:
                response = await asyncio.to_thread(
                    gemini_client.models.generate_content,
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                reply = response.text.strip()
            except Exception as e:
                await message.reply(f"Error: {e}")
                continue

        chunks = [reply[i:i+CHUNK_SIZE] for i in range(0, len(reply), CHUNK_SIZE)]
        for chunk in chunks:
            await message.reply(chunk)
        add_to_memory("Beanie", reply)
        
        # Garbage collect after AI response
        gc.collect()
    
    ai_processing = False

# --- SLASH COMMANDS ---

# Birthday Commands
@tree.command(name="birthday", description="Manage birthdays")
@app_commands.describe(
    action="Action: add or list",
    user="User to add birthday for (required for 'add')",
    date="Birthday date in dd/mm format (required for 'add')"
)
async def birthday_cmd(interaction: discord.Interaction, action: str, user: discord.Member = None, date: str = None):
    """Birthday management (admin only)."""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only command.", ephemeral=True)
        return
    
    if action.lower() == "add":
        if not user or not date:
            await interaction.response.send_message("❌ Usage: /birthday add [user] [dd/mm]", ephemeral=True)
            return
        
        # Validate date format
        if not date or len(date.split("/")) != 2:
            await interaction.response.send_message("❌ Invalid date! Use dd/mm format (e.g., 25/12)", ephemeral=True)
            return
        
        birthdays = load_birthdays()
        birthdays[str(user.id)] = date
        save_birthdays(birthdays)
        
        await interaction.response.send_message(f"✅ Birthday for {user.display_name} set to {date}!", ephemeral=True)
        gc.collect()
    
    elif action.lower() == "list":
        birthdays = load_birthdays()
        if not birthdays:
            await interaction.response.send_message("📅 No birthdays registered yet.", ephemeral=True)
            return
        
        msg = "📅 **Registered Birthdays:**\n"
        for user_id, date_str in birthdays.items():
            try:
                member = await bot.fetch_user(int(user_id))
                name = member.display_name if member else f"<@{user_id}>"
            except:
                name = f"<@{user_id}>"
            msg += f"• {name}: {date_str}\n"
        
        await interaction.response.send_message(msg, ephemeral=True)
        gc.collect()
    
    else:
        await interaction.response.send_message("❌ Invalid action! Use 'add' or 'list'.", ephemeral=True)

# Rank Competition Commands
@tree.command(name="rank", description="Join or manage voice time competition")
@app_commands.describe(
    action="Action: add, remove, or list",
    user="User to add/remove from competition (leave empty to add yourself)"
)
async def rank_cmd(interaction: discord.Interaction, action: str, user: discord.Member = None):
    """Manage voice time competition list. Anyone can join, admin can manage others."""
    
    # Try to defer; if it fails (unknown interaction / already acknowledged), fall back to immediate ack
    deferred = False
    ack_sent = False
    try:
        await interaction.response.defer(ephemeral=True)
        deferred = True
    except Exception as e:
        logging.warning(f"Interaction defer failed for /rank: {e}")
        try:
            await interaction.response.send_message("✅ Processing...", ephemeral=True)
            ack_sent = True
        except Exception:
            logging.warning("Fallback immediate ack also failed for /rank")
    
    if action.lower() == "add":
        # If no user specified, add the person who ran the command
        target_user = user if user else interaction.user
        user_id = str(target_user.id)
        
        # Admin check only if adding someone else
        if user and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You can only add yourself. Use `/rank add` without specifying a user.", ephemeral=True)
            return
        
        competitors = load_competitors()
        
        if user_id in competitors:
            await interaction.followup.send(f"⚠️ {target_user.display_name} is already in the competition.", ephemeral=True)
            return
        
        # Checkpoint: Initialize stats for new competitor if they don't have any
        stats = load_voice_stats()
        if user_id not in stats:
            stats[user_id] = 0
            save_voice_stats(stats)
        
        # Create voice channel in the specified category
        try:
            category = bot.get_channel(RANK_CATEGORY_ID)
            if not category:
                await interaction.followup.send("❌ Rank category not found. Please check RANK_CATEGORY_ID.", ephemeral=True)
                return
            
            # Get current totals for initial display
            total_hours = stats.get(user_id, 0) / 3600
            
            # Create channel with current stats
            new_channel = await category.create_voice_channel(
                name=f"🏅 {target_user.display_name}: {int(total_hours)}h",
                reason=f"Rank channel for {target_user.display_name}"
            )
            
            # Add to competitors
            competitors[user_id] = str(new_channel.id)
            save_competitors(competitors)
            
            await interaction.followup.send(f"✅ {target_user.display_name} joined the competition! Channel created: {new_channel.mention}", ephemeral=True)
            gc.collect()
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to create channel: {e}", ephemeral=True)
            logging.error(f"Failed to create rank channel: {e}")
    
    elif action.lower() == "remove":
        # Admin check for removing others
        if user and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Only admins can remove other users.", ephemeral=True)
            return
        
        target_user = user if user else interaction.user
        user_id = str(target_user.id)
        
        competitors = load_competitors()
        
        if user_id not in competitors:
            await interaction.followup.send(f"⚠️ {target_user.display_name} is not in the competition.", ephemeral=True)
            return
        
        # Delete the channel
        channel_id = competitors[user_id]
        if channel_id:
            try:
                channel = bot.get_channel(int(channel_id))
                if channel:
                    await channel.delete(reason=f"Removed {target_user.display_name} from competition")
            except Exception as e:
                logging.error(f"Failed to delete channel {channel_id}: {e}")
        
        del competitors[user_id]
        save_competitors(competitors)
        
        await interaction.followup.send(f"✅ {target_user.display_name} removed from voice time competition.", ephemeral=True)
        gc.collect()
    
    elif action.lower() == "list":
        # Checkpoint: Update stats for people currently in voice before displaying
        checkpoint_voice_stats()
        
        competitors = load_competitors()
        if not competitors:
            await interaction.followup.send("📊 No competitors registered yet.", ephemeral=True)
            return
        
        # Get all-time totals (aggregate current stats + archived months)
        stats = load_all_time_stats()

        rankings = []
        for uid, channel_id in competitors.items():
            total_seconds = stats.get(uid, 0)
            total_hours = total_seconds / 3600
            rankings.append((int(uid), total_hours))
        
        rankings.sort(key=lambda x: x[1], reverse=True)
        
        msg = "📊 **Voice Time Competition - All-Time Leaderboard:**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, hours) in enumerate(rankings):
            try:
                member = await bot.fetch_user(uid)
                name = member.display_name if member else f"<@{uid}>"
            except:
                name = f"<@{uid}>"
            
            medal = medals[i] if i < len(medals) else f"#{i+1}"
            msg += f"{medal} **{name}**: {int(hours)}h {int((hours % 1) * 60)}m\n"
        
        await interaction.followup.send(msg, ephemeral=True)
        gc.collect()
    
    else:
        await interaction.followup.send("❌ Invalid action! Use 'add', 'remove', or 'list'.", ephemeral=True)

# Say Command (Gold+)
@tree.command(name="say", description="Make Beanie speak in your voice channel (Gold+ rank)")
@app_commands.describe(message="Text message to speak (max 50 characters)")
async def say_cmd(interaction: discord.Interaction, message: str):
    """Text-to-speech command for Gold+ ranked users."""
    # Defer but handle possible interaction errors (Unknown interaction / Already acknowledged)
    deferred = False
    ack_sent = False
    try:
        await interaction.response.defer(ephemeral=True)
        deferred = True
    except Exception as e:
        logging.warning(f"Interaction defer failed for /say: {e}")
        try:
            await interaction.response.send_message("✅ Received, processing...", ephemeral=True)
            ack_sent = True
        except Exception as e2:
            logging.warning(f"Fallback send_message failed for /say: {e2}")
    
    user_id = str(interaction.user.id)
    
    # Check rank
    stats = load_voice_stats()
    total_seconds = stats.get(user_id, 0)
    total_hours = total_seconds / 3600
    rank_name, role_id, perks = get_user_rank(total_hours)
    
    # Must be Gold+ rank
    if rank_name not in ["Gold", "Platinum", "Diamond", "Elite", "Immortal", "Legendary"]:
        await interaction.followup.send(f"❌ Chỉ Gold rank trở lên mới dùng được /say! (Rank hiện tại: {rank_name})", ephemeral=True)
        return
    
    # Check cooldown
    now = time.time()
    last_use = say_cooldowns.get(user_id, 0)
    if now - last_use < 5:
        remaining = 5 - (now - last_use)
        await interaction.followup.send(f"⏳ Cooldown: chờ {remaining:.1f}s nữa!", ephemeral=True)
        return
    
    # Validate message length
    if len(message) > 50:
        await interaction.followup.send("❌ Message quá dài! Tối đa 50 characters.", ephemeral=True)
        return
    
    # Check if user is in voice channel
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ Bạn phải ở trong voice channel!", ephemeral=True)
        return
    
    # Try to add to queue
    try:
        say_queue.put_nowait((interaction, message))
        say_cooldowns[user_id] = now
        # Send confirmation: if we already sent an ack, skip followup
        if not ack_sent:
            try:
                if deferred:
                    await interaction.followup.send(f"✅ Đã thêm vào hàng đợi: '{message}'", ephemeral=True)
                else:
                    await interaction.response.send_message(f"✅ Đã thêm vào hàng đợi: '{message}'", ephemeral=True)
            except Exception:
                logging.warning("Failed to send confirmation for /say; proceeding silently")
    except asyncio.QueueFull:
        try:
            if deferred:
                await interaction.followup.send("❌ Bot đang quá tải audio, chờ xíu!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Bot đang quá tải audio, chờ xíu!", ephemeral=True)
        except Exception:
            logging.warning("Failed to send queue-full response for /say")

# Entry Command Group (Diamond+)
entry_group = app_commands.Group(name="entry", description="Manage entrance sound settings")

@entry_group.command(name="on", description="Enable entrance sound (Diamond+ rank)")
async def entry_on(interaction: discord.Interaction):
    """Enable entrance sound for Diamond+ users."""
    user_id = str(interaction.user.id)
    
    # Check rank
    stats = load_voice_stats()
    total_seconds = stats.get(user_id, 0)
    total_hours = total_seconds / 3600
    rank_name, role_id, perks = get_user_rank(total_hours)
    
    if rank_name not in ["Diamond", "Elite", "Immortal", "Legendary"]:
        await interaction.response.send_message(f"❌ Chỉ Diamond rank trở lên mới có entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
        return
    
    entry_settings = load_entry_settings()
    if user_id not in entry_settings:
        entry_settings[user_id] = {"enabled": True, "type": "default"}
    else:
        entry_settings[user_id]["enabled"] = True
    save_entry_settings(entry_settings)
    
    await interaction.response.send_message("✅ Entrance sound đã BẬT!", ephemeral=True)

@entry_group.command(name="off", description="Disable entrance sound (Diamond+ rank)")
async def entry_off(interaction: discord.Interaction):
    """Disable entrance sound for Diamond+ users."""
    user_id = str(interaction.user.id)
    
    # Check rank
    stats = load_voice_stats()
    total_seconds = stats.get(user_id, 0)
    total_hours = total_seconds / 3600
    rank_name, role_id, perks = get_user_rank(total_hours)
    
    if rank_name not in ["Diamond", "Elite", "Immortal", "Legendary"]:
        await interaction.response.send_message(f"❌ Chỉ Diamond rank trở lên mới có entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
        return
    
    entry_settings = load_entry_settings()
    if user_id not in entry_settings:
        entry_settings[user_id] = {"enabled": False, "type": "default"}
    else:
        entry_settings[user_id]["enabled"] = False
    save_entry_settings(entry_settings)
    
    await interaction.response.send_message("✅ Entrance sound đã TẮT!", ephemeral=True)

@entry_group.command(name="add", description="Add custom entrance sound (Immortal+ rank)")
async def entry_add(interaction: discord.Interaction):
    """Add custom entrance sound for Immortal+ users."""
    user_id = str(interaction.user.id)
    
    # Check rank
    stats = load_voice_stats()
    total_seconds = stats.get(user_id, 0)
    total_hours = total_seconds / 3600
    rank_name, role_id, perks = get_user_rank(total_hours)
    
    if rank_name not in ["Immortal", "Legendary"]:
        await interaction.response.send_message(f"❌ Chỉ Immortal rank trở lên mới tùy chỉnh entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
        return
    
    # Show button view
    view = EntryCustomizeView(user_id)
    await interaction.response.send_message("🎵 Chọn cách tùy chỉnh entrance sound:", view=view, ephemeral=True)

@entry_group.command(name="upload", description="Upload custom audio file (Immortal+ rank)")
@app_commands.describe(file="Audio file (.mp3 or .ogg, max 200KB)")
async def entry_upload(interaction: discord.Interaction, file: discord.Attachment):
    """Upload custom audio file for entrance sound."""
    await interaction.response.defer(ephemeral=True)
    
    user_id = str(interaction.user.id)
    
    # Check rank
    stats = load_voice_stats()
    total_seconds = stats.get(user_id, 0)
    total_hours = total_seconds / 3600
    rank_name, role_id, perks = get_user_rank(total_hours)
    
    if rank_name not in ["Immortal", "Legendary"]:
        await interaction.followup.send(f"❌ Chỉ Immortal rank trở lên mới upload custom audio! (Rank hiện tại: {rank_name})", ephemeral=True)
        return
    
    # Validate file size
    if file.size > 200 * 1024:  # 200KB
        await interaction.followup.send(f"❌ File quá lớn! Tối đa 200KB (file của bạn: {file.size // 1024}KB)", ephemeral=True)
        return
    
    # Validate file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".mp3", ".ogg"]:
        await interaction.followup.send("❌ Chỉ hỗ trợ .mp3 hoặc .ogg!", ephemeral=True)
        return
    
    # Delete old custom files
    for old_ext in [".mp3", ".ogg"]:
        old_file = f"sfx/custom_{user_id}{old_ext}"
        try:
            if os.path.exists(old_file):
                os.remove(old_file)
        except Exception as e:
            logging.warning(f"Failed to delete old custom file {old_file}: {e}")
    
    # Save new file
    custom_file = f"sfx/custom_{user_id}{ext}"
    try:
        await file.save(custom_file)
        
        # Update settings
        entry_settings = load_entry_settings()
        entry_settings[user_id] = {"enabled": True, "type": "file"}
        save_entry_settings(entry_settings)
        
        await interaction.followup.send(f"✅ Đã upload custom entrance sound! ({file.filename})", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Upload failed: {e}", ephemeral=True)

# Register entry command group
tree.add_command(entry_group)

# UI View for entry customization
class EntryCustomizeView(discord.ui.View):
    __slots__ = ('user_id',)
    
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
    
    @discord.ui.button(label="Nhập TTS", style=discord.ButtonStyle.primary, emoji="💬")
    async def tts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Show modal for TTS input
        modal = EntryTTSModal(self.user_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Upload File", style=discord.ButtonStyle.secondary, emoji="📁")
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📁 Sử dụng lệnh `/entry upload` kèm file .mp3 (Max 200KB)",
            ephemeral=True
        )

class EntryTTSModal(discord.ui.Modal, title="Custom TTS Entrance"):
    __slots__ = ('user_id',)
    
    tts_text = discord.ui.TextInput(
        label="Nhập text cho TTS",
        placeholder="Xin chào...",
        max_length=50,
        required=True
    )
    
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        text = self.tts_text.value.strip()
        if not text:
            await interaction.followup.send("❌ Text không được để trống!", ephemeral=True)
            return
        
        # Delete old custom files
        for old_ext in [".mp3", ".ogg"]:
            old_file = f"sfx/custom_{self.user_id}{old_ext}"
            try:
                if os.path.exists(old_file):
                    os.remove(old_file)
            except Exception as e:
                logging.warning(f"Failed to delete old custom file {old_file}: {e}")
        
        # Generate TTS file
        custom_file = f"sfx/custom_{self.user_id}.mp3"
        try:
            tts = gTTS(text=text, lang='vi', slow=False)
            await asyncio.to_thread(tts.save, custom_file)
            
            # Update settings
            entry_settings = load_entry_settings()
            entry_settings[self.user_id] = {"enabled": True, "type": "tts", "text": text}
            save_entry_settings(entry_settings)
            
            await interaction.followup.send(f"✅ Đã tạo custom TTS entrance: '{text}'", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ TTS generation failed: {e}", ephemeral=True)

# Minecraft Commands (keeping all existing)
@tree.command(name="status", description="Check Azure VM and Minecraft server status")
async def status_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    msg = ""
    try:
        if compute_client:
            vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
            vm_status = vm.instance_view.statuses[1].display_status
            msg += f"🖥️ **Azure VM:** {vm_status}\n"
        else:
            msg += "🖥️ **Azure VM:** Not configured\n"
    except Exception as e:
        msg += f"🖥️ **Azure VM:** Error - {e}\n"
    try:
        players_cnt = None
        if vm_is_running() and RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
            try:
                out = await asyncio.wait_for(asyncio.to_thread(rcon_command, "list"), timeout=5)
                import re
                m = re.search(r"There are (\d+) of a max", out)
                if m:
                    players_cnt = int(m.group(1))
                    msg += f"🟢 **Minecraft (RCON):** {players_cnt} players\n"
                else:
                    msg += "🟡 **Minecraft (RCON):** Unable to parse player count\n"
            except Exception:
                players_cnt = None
        if players_cnt is None:
            if MC_SERVER_IP:
                server = JavaServer.lookup(MC_SERVER_IP)
                status_mc = server.status()
                msg += f"🟢 **Minecraft:** Online ({status_mc.players.online} players) — Ping {int(status_mc.latency)}ms"
            else:
                msg += "⚫ **Minecraft:** IP not configured"
    except Exception:
        msg += "⚫ **Minecraft:** Offline or starting"
    try:
        if LAST_REQUEST_CHANNEL_ID:
            msg += f"\n🔔 **Requested by channel:** <#{LAST_REQUEST_CHANNEL_ID}>"
    except Exception:
        pass
    await interaction.followup.send(msg)


@tree.command(name="refresh_leaderboard", description="(Admin) Force refresh voice leaderboard now")
async def refresh_leaderboard(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        # checkpoint and run update immediately
        checkpoint_voice_stats()
        await update_leaderboard()
        await interaction.followup.send("✅ Leaderboard refreshed.", ephemeral=True)
    except Exception as e:
        logging.error(f"Manual leaderboard refresh failed: {e}")
        await interaction.followup.send(f"❌ Refresh failed: {e}", ephemeral=True)

@tree.command(name="start", description="Start Azure VM and Minecraft server")
async def start_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    global LAST_REQUEST_CHANNEL_ID
    try:
        LAST_REQUEST_CHANNEL_ID = interaction.channel_id
        with open(LAST_REQUEST_CHANNEL_FILE, "w", encoding="utf-8") as f:
            f.write(str(LAST_REQUEST_CHANNEL_ID))
    except Exception as e:
        logging.warning(f"Could not persist last request channel: {e}")
    if not compute_client:
        await interaction.followup.send("❌ Azure chưa được cấu hình. Kiểm tra biến môi trường.")
        return
    loop = asyncio.get_running_loop()
    await interaction.followup.send("1️⃣ Bật Azure VM...")
    try:
        await loop.run_in_executor(None, azure_start_vm)
    except Exception as e:
        await interaction.followup.send(f"Lỗi khi bật VM: {e}")
        return
    await interaction.followup.send("✅ VM đã bật. Đợi 30s cho OS khởi động...")
    await asyncio.sleep(30)
    try:
        if not auto_shutdown_check.is_running():
            auto_shutdown_check.start()
    except Exception:
        pass
    await interaction.followup.send("2️⃣ Bật Minecraft server...")
    cmd = 'bash -lc "cd ~/minecraft && screen -dmS mc ./run.sh"'
    out = await asyncio.to_thread(ssh_command, cmd)
    await interaction.followup.send(f"✅ Lệnh khởi động đã gửi: {out[:1000]}")
    start_poll = time.time()
    server_online = False
    while time.time() - start_poll < SHUTDOWN_MAX_WAIT:
        try:
            if MC_SERVER_IP:
                server = JavaServer.lookup(MC_SERVER_IP)
                status_mc = server.status()
                server_online = True
                players_online = status_mc.players.online
                latency = int(status_mc.latency)
            else:
                server_online = False
        except Exception:
            server_online = False
        if server_online:
            msg = ""
            try:
                if compute_client:
                    vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
                    vm_status = vm.instance_view.statuses[1].display_status
                    msg += f"🖥️ **Azure VM:** {vm_status}\n"
                else:
                    msg += "🖥️ **Azure VM:** Not configured\n"
            except Exception as e:
                msg += f"🖥️ **Azure VM:** Error - {e}\n"
            players_cnt = None
            if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD and vm_is_running():
                try:
                    out_r = await asyncio.wait_for(asyncio.to_thread(rcon_command, "list"), timeout=5)
                    import re
                    m = re.search(r"There are (\d+) of a max", out_r)
                    if m:
                        players_cnt = int(m.group(1))
                except Exception:
                    players_cnt = None
            if players_cnt is None:
                msg += f"🟢 **Minecraft:** Online ({players_online} players) — Ping {latency}ms"
            else:
                msg += f"🟢 **Minecraft (RCON):** {players_cnt} players"
            await interaction.followup.send(msg)
            try:
                global MANUAL_GRACE_UNTIL
                MANUAL_GRACE_UNTIL = time.time() + (MANUAL_GRACE_MINUTES * 60)
            except Exception:
                pass
            break
        await asyncio.sleep(5)
    if not server_online:
        await interaction.followup.send("⚠️ Máy chủ vẫn chưa online sau thời gian chờ; có thể server vẫn đang khởi động. Vui lòng kiểm tra lại sau.")

@tree.command(name="stop", description="Stop Minecraft server and deallocate VM (Smart Force)")
async def stop_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    
    if not vm_is_running():
        await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to stop.")
        return
    
    await interaction.followup.send("🛑 Đang gửi lệnh tắt server...")
    
    if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
        try:
            await asyncio.to_thread(rcon_command, 'stop')
        except:
            pass
    await asyncio.to_thread(ssh_command, 'screen -S mc -p 0 -X stuff "stop^M"')
    
    await interaction.followup.send("⏳ Đang chờ server lưu dữ liệu và tắt (45s)...")
    
    confirmed = await asyncio.to_thread(wait_for_mc_shutdown, 45, 5)
    
    if not confirmed:
        await interaction.followup.send("⚠️ Server có vẻ bị treo (Freeze) sau 45s. Đang thực hiện Force Kill (pkill)...")
        await asyncio.to_thread(ssh_command, 'pkill -9 -f java')
        await asyncio.sleep(5)
        confirmed = await asyncio.to_thread(wait_for_mc_shutdown, 10, 2)
    
    if confirmed:
        if compute_client:
            loop = asyncio.get_running_loop()
            await interaction.followup.send("2️⃣ Minecraft đã tắt. Đang tắt Azure VM...")
            try:
                await loop.run_in_executor(None, azure_stop_vm)
                await interaction.followup.send("💤 Hệ thống đã tắt hoàn toàn.")
            except Exception as e:
                await interaction.followup.send(f"Lỗi khi tắt VM: {e}")
        else:
            await interaction.followup.send("Azure không được cấu hình; chỉ gửi lệnh stop đến MC.")
    else:
        await interaction.followup.send("❌ CỰC KỲ NGUY HIỂM: Không thể tắt process Java dù đã Force Kill. VM sẽ GIỮ NGUYÊN để bạn kiểm tra.")

@tree.command(name="restart_mc", description="Restart Minecraft server only")
async def restart_mc_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    if not vm_is_running():
        await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to restart.")
        return
    await interaction.followup.send("🔄 Force restarting Minecraft server (killing JVM, then starting)...")
    if SSH_PASSWORD and SSH_HOST and SSH_USER:
        cmd = 'bash -lc "pkill -9 -f java || true; sleep 2; cd ~/minecraft && screen -dmS mc ./run.sh"'
        out = await asyncio.to_thread(ssh_command, cmd)
        await interaction.followup.send(f"✅ Force restart command executed: {str(out)[:1000]}")
        try:
            global MANUAL_GRACE_UNTIL
            MANUAL_GRACE_UNTIL = time.time() + (MANUAL_GRACE_MINUTES * 60)
        except Exception:
            pass
        return
    if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
        try:
            await asyncio.to_thread(rcon_command, 'stop')
            await asyncio.sleep(5)
            await interaction.followup.send("✅ Sent RCON stop (graceful). Note: server start requires SSH access to run the start script.")
            return
        except Exception as e:
            await interaction.followup.send(f"⚠️ RCON stop failed: {e} and SSH not configured — cannot force restart.")
            return
    await interaction.followup.send("⚠️ Không thể thực hiện restart: SSH và RCON đều không được cấu hình.")

@tree.command(name="wipe", description="(Admin) Wipe Beanie's memory")
async def wipe(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You need admin rights to use this.", ephemeral=True)
        return
    clear_memory()
    await interaction.response.send_message("Beanie's memory wiped!", ephemeral=True)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)