# --- ALL IMPORTS AT TOP ---
import os
from dotenv import load_dotenv
import logging
import time
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button
## Removed music features: lyricsgenius, yt_dlp
import google.generativeai as genai
import paramiko
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from mcstatus import JavaServer
try:
	from mcrcon import MCRcon
	RCON_PKG_AVAILABLE = True
except Exception:
	RCON_PKG_AVAILABLE = False
from datetime import datetime, timedelta, timezone
import pytz


# --- CONFIG & CONSTANTS ---
load_dotenv()
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # Set your Discord bot token as env var
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # Set your Gemini API key as env var
GENIUS_API_KEY = os.getenv("GENIUS_ACCESS_TOKEN")
MEMORY_LIMIT = 200  # Max messages in context
WARNING_THRESHOLD = 194  # Warn at this many messages
COOLDOWN_MINUTES = 60
CHUNK_SIZE = 1900  # Discord message chunk size

# --- Azure & SSH ENV ---
AZURE_SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
AZURE_RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP")
AZURE_VM_NAME = os.getenv("AZURE_VM_NAME")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")

SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
MC_SERVER_IP = os.getenv("MC_SERVER_IP")

# Shutdown verification settings
SHUTDOWN_MAX_WAIT = int(os.getenv("SHUTDOWN_MAX_WAIT", "300"))
SHUTDOWN_POLL_INTERVAL = int(os.getenv("SHUTDOWN_POLL_INTERVAL", "3"))

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

# Azure compute client (optional)
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
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel('models/gemini-2.5-flash')



# --- Bot Setup (must be before any @tree.command or @bot.event) ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Optional: set a testing guild for immediate slash command sync (set GUILD_ID in .env)
GUILD_ID = int(os.getenv("GUILD_ID") or 0)


## Removed MusicControls and all music queue/player logic


# --- Music Queue and Player ---

## Removed all music queue/player/lyrics/commands and events


# --- Shared State ---
chat_memory = []  # List of {user, content, time}
lockdown = False
lockdown_until = None

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

def add_to_memory(user, content):
	global chat_memory
	now_vn = datetime.now(VIETNAM_TZ)
	chat_memory.append({"user": user, "content": content, "time": now_vn})
	if len(chat_memory) > MEMORY_LIMIT:
		chat_memory.pop(0)

	# Save chat history to file (auto-trim to MEMORY_LIMIT)
	try:
		# Read current history
		if os.path.exists("chat_history.txt"):
			with open("chat_history.txt", "r", encoding="utf-8") as f:
				lines = f.readlines()
		else:
			lines = []
		# Add new line
		lines.append(f"[{datetime.utcnow().isoformat()}] {user}: {content}\n")
		# Trim to MEMORY_LIMIT
		if len(lines) > MEMORY_LIMIT:
			lines = lines[-MEMORY_LIMIT:]
		# Write back
		with open("chat_history.txt", "w", encoding="utf-8") as f:
			f.writelines(lines)
	except Exception as e:
		logging.error(f"Failed to write chat history: {e}")


# --- Helper functions for Azure and SSH ---
def azure_start_vm():
	"""Start Azure VM (blocking)."""
	if not compute_client:
		raise RuntimeError("Azure not configured")
	async_action = compute_client.virtual_machines.begin_start(AZURE_RESOURCE_GROUP, AZURE_VM_NAME)
	async_action.wait()

def azure_stop_vm():
	"""Deallocate Azure VM (blocking)."""
	if not compute_client:
		raise RuntimeError("Azure not configured")
	async_action = compute_client.virtual_machines.begin_deallocate(AZURE_RESOURCE_GROUP, AZURE_VM_NAME)
	async_action.wait()


def vm_is_running():
	"""Return True if Azure VM is in running state."""
	if not compute_client:
		return False
	try:
		vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
		return "running" in vm.instance_view.statuses[1].display_status.lower()
	except Exception:
		return False

def ssh_command(command, timeout=10):
	"""Execute a command over SSH using a private key file."""
	# Simplified SSH: use password-based auth only. Key-based auth removed per user preference.
	try:
		c = paramiko.SSHClient()
		c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		# Only allow password auth now
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
	"""Blocking helper: verify Minecraft has stopped.

	Prefer SSH check (screen session named 'mc') if SSH_PASSWORD is configured.
	Fallback to mcstatus (network check) if no SSH available.
	Returns True if server confirmed stopped within timeout, False otherwise.
	"""
	import time
	start = time.time()
	# If SSH available, check screen session 'mc'
	if SSH_PASSWORD and SSH_HOST and SSH_USER:
		while time.time() - start < max_wait:
			try:
				# echo RUNNING or STOPPED
				cmd = 'bash -lc "screen -ls | grep mc >/dev/null && echo RUNNING || echo STOPPED"'
				out = ssh_command(cmd, timeout=5)
				if isinstance(out, str) and out.strip().startswith("STOPPED"):
					return True
			except Exception:
				pass
			time.sleep(poll_interval)
		return False

	# Fallback: use mcstatus network check
	if MC_SERVER_IP:
		while time.time() - start < max_wait:
			try:
				server = JavaServer.lookup(MC_SERVER_IP)
				_ = server.status()
				# still up
			except Exception:
				return True
			time.sleep(poll_interval)
		return False

	# no method to verify; return False
	return False


def rcon_command(command, timeout=10):
	"""Blocking helper to send an RCON command.

	This function is synchronous because the underlying MCRcon client is blocking.
	Call it from async code using `await asyncio.wait_for(asyncio.to_thread(rcon_command, cmd), timeout=...)`.
	"""
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

def clear_memory():
	global chat_memory
	chat_memory = []

def check_lockdown():
	global lockdown, lockdown_until
	now_vn = datetime.now(VIETNAM_TZ)
	if lockdown and lockdown_until and now_vn >= lockdown_until:
		lockdown = False
		lockdown_until = None
		clear_memory()
		return True
	return False

@tasks.loop(minutes=1)
async def cooldown_check():
	if check_lockdown():
		for guild in bot.guilds:
			for channel in guild.text_channels:
				try:
					await channel.send("🔔 AI Chat is available now!")
				except:
					continue

@bot.event
async def on_ready():
		print(f"Logged in as {bot.user}")
		try:
			if GUILD_ID:
				guild_obj = discord.Object(id=GUILD_ID)
				# copy any global commands to the guild to make them appear instantly
				try:
					await tree.copy_global_to(guild=guild_obj)
				except Exception:
					pass
				synced = await tree.sync(guild=guild_obj)
				print(f"Synced {len(synced)} commands to guild {GUILD_ID}.")
			else:
				synced = await tree.sync()
				print(f"Synced {len(synced)} global commands.")

			# debug: list registered app commands
			try:
				cmds = [c.name for c in tree.get_commands()]
				print(f"App commands registered in tree: {cmds}")
			except Exception:
				pass
		except Exception as e:
			print(f"Sync error: {e}")
		cooldown_check.start()
		# start auto shutdown checker if azure/mc configured
		try:
			auto_shutdown_check.start()
		except RuntimeError:
			# already started or not configured
			pass

		# load last request channel if exists
		global LAST_REQUEST_CHANNEL_ID
		try:
			if os.path.exists(LAST_REQUEST_CHANNEL_FILE):
				with open(LAST_REQUEST_CHANNEL_FILE, "r", encoding="utf-8") as f:
					val = f.read().strip()
					if val:
						LAST_REQUEST_CHANNEL_ID = int(val)
		except Exception as e:
			logging.warning(f"Could not load last request channel: {e}")


# --- Global AI queue ---
ai_queue = asyncio.Queue()
ai_processing = False


# --- Listen for /beanie text messages ---
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

		# Warning and Lockdown logic
		if len(chat_memory) == WARNING_THRESHOLD:
			await message.channel.send("⚠️ You have 3 messages left, make them worthy!")
		if len(chat_memory) >= MEMORY_LIMIT:
			lockdown = True
			now_vn = datetime.now(VIETNAM_TZ)
			lockdown_until = now_vn + timedelta(minutes=COOLDOWN_MINUTES)
			await message.channel.send("🔒 AI Chat is now locked for 1 hour! (Vietnam time)")
			continue

		# Show typing indicator while generating response
		async with message.channel.typing():
			# Prepare system prompt for friendly, creative, Vietnamese-style responses
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
				response = await asyncio.to_thread(gemini.generate_content, prompt)
				reply = response.text.strip()
			except Exception as e:
				await message.reply(f"Error: {e}")
				continue

		# Split and send in chunks
		chunks = [reply[i:i+CHUNK_SIZE] for i in range(0, len(reply), CHUNK_SIZE)]
		for chunk in chunks:
			await message.reply(chunk)
		add_to_memory("Beanie", reply)
	ai_processing = False


# --- Azure/Minecraft control commands ---
@commands.hybrid_command(name="status", description="Check Azure VM and Minecraft server status")
async def status(ctx):
	"""Check Azure VM and Minecraft server status"""
	await ctx.defer()
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
		# Prefer RCON for accurate info if enabled, else mcstatus
		players_cnt = None
		if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
			try:
				# run rcon in thread with a short timeout
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

	# include which channel requested last start (if any)
	try:
		if LAST_REQUEST_CHANNEL_ID:
			msg += f"\n🔔 **Requested by channel:** <#{LAST_REQUEST_CHANNEL_ID}>"
	except Exception:
		pass

	# send as followup if invoked as slash, else normal send
	try:
		await ctx.followup.send(msg)
	except Exception:
		await ctx.send(msg)
# Note: `status` is provided as an explicit slash command via `status_slash` below.


@commands.hybrid_command(name="start", description="Start Azure VM and Minecraft server")
async def start(ctx):
	"""Start full stack: Azure VM -> wait -> start MC via SSH"""
	await ctx.defer()
	# record which channel requested the start
	global LAST_REQUEST_CHANNEL_ID
	try:
		LAST_REQUEST_CHANNEL_ID = ctx.channel.id
		with open(LAST_REQUEST_CHANNEL_FILE, "w", encoding="utf-8") as f:
			f.write(str(LAST_REQUEST_CHANNEL_ID))
	except Exception as e:
		logging.warning(f"Could not persist last request channel: {e}")
	if not compute_client:
		try:
			await ctx.followup.send("❌ Azure chưa được cấu hình. Kiểm tra biến môi trường.")
		except Exception:
			await ctx.send("❌ Azure chưa được cấu hình. Kiểm tra biến môi trường.")
		return
	loop = asyncio.get_running_loop()
	try:
		await ctx.followup.send("1️⃣ Bật Azure VM...")
	except Exception:
		await ctx.send("1️⃣ Bật Azure VM...")
	try:
		await loop.run_in_executor(None, azure_start_vm)
	except Exception as e:
		try:
			await ctx.followup.send(f"Lỗi khi bật VM: {e}")
		except Exception:
			await ctx.send(f"Lỗi khi bật VM: {e}")
		return
	# ensure auto-shutdown checker is running after VM is started
	try:
		if not auto_shutdown_check.is_running():
			auto_shutdown_check.start()
	except Exception:
		pass
	try:
		await ctx.followup.send("✅ VM đã bật. Đợi 30s cho OS khởi động...")
	except Exception:
		await ctx.send("✅ VM đã bật. Đợi 30s cho OS khởi động...")
	await asyncio.sleep(30)
	try:
		await ctx.followup.send("2️⃣ Bật Minecraft server...")
	except Exception:
		await ctx.send("2️⃣ Bật Minecraft server...")
	# try RCON 'say' or 'start' is not applicable; use SSH to start background script
	cmd = "cd ~/minecraft && screen -dmS mc ./start.sh"
	out = await asyncio.to_thread(ssh_command, cmd)
	try:
		await ctx.followup.send(f"✅ Lệnh khởi động đã gửi: {out[:1000]}")
	except Exception:
		await ctx.send(f"✅ Lệnh khởi động đã gửi: {out[:1000]}")
	# notify the channel that requested start (explicit confirmation)
	try:
		await ctx.channel.send("✅ Server đang khởi động. Đang theo dõi trạng thái server (kiểm tra mỗi 5s)...")
	except Exception:
		pass
	# Poll mcstatus every 5s until online or timeout
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
			# Build a short status message similar to /status
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
			# prefer RCON for exact player count when available
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
			try:
				await ctx.followup.send(msg)
			except Exception:
				await ctx.send(msg)
			break
		await asyncio.sleep(5)
	if not server_online:
		try:
			await ctx.followup.send("⚠️ Máy chủ vẫn chưa online sau thời gian chờ; có thể server vẫn đang khởi động. Vui lòng kiểm tra lại sau.")
		except Exception:
			await ctx.send("⚠️ Máy chủ vẫn chưa online sau thời gian chờ; có thể server vẫn đang khởi động. Vui lòng kiểm tra lại sau.")
# Note: `start` is provided as an explicit slash command via `start_slash` below.


@commands.hybrid_command(name="stop", description="Stop Minecraft server and deallocate VM")
async def stop(ctx):
	"""Stop Minecraft gracefully then deallocate VM"""
	await ctx.defer()
	try:
		await ctx.followup.send("🛑 Đang tắt server...")
	except Exception:
		await ctx.send("🛑 Đang tắt server...")
	# stop MC: prefer RCON if available, fallback to SSH
	stopped = False
	# If VM is not running, nothing to do
	if not vm_is_running():
		try:
			await ctx.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to stop.")
		except Exception:
			await ctx.send("⚫ **Azure VM:** already deallocated/offline — nothing to stop.")
		return
	if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
		try:
			out = await asyncio.wait_for(asyncio.to_thread(rcon_command, 'stop'), timeout=5)
			try:
				await ctx.followup.send(f"✅ Đã gửi lệnh stop via RCON: {str(out)[:1000]}")
			except Exception:
				await ctx.send(f"✅ Đã gửi lệnh stop via RCON: {str(out)[:1000]}")
			stopped = True
		except Exception as e:
			try:
				await ctx.followup.send(f"⚠️ RCON stop failed: {e}. Falling back to SSH...")
			except Exception:
				await ctx.send(f"⚠️ RCON stop failed: {e}. Falling back to SSH...")
	if not stopped:
		try:
			out_ssh = await asyncio.to_thread(ssh_command, 'screen -S mc -p 0 -X stuff "stop^M"')
			# if SSH is disabled, return early
			if out_ssh == "SSH disabled: no SSH_PASSWORD configured":
				try:
					await ctx.followup.send("⚠️ SSH not configured; cannot send stop. If server is running, enable RCON or SSH.")
				except Exception:
					await ctx.send("⚠️ SSH not configured; cannot send stop. If server is running, enable RCON or SSH.")
				return
		except Exception as e:
			try:
				await ctx.followup.send(f"Lỗi gửi lệnh stop qua SSH: {e}")
			except Exception:
				await ctx.send(f"Lỗi gửi lệnh stop qua SSH: {e}")
	try:
		await ctx.followup.send("⏳ Đang chờ Minecraft tắt (tối đa 60s)...")
	except Exception:
		await ctx.send("⏳ Đang chờ Minecraft tắt (tối đa 60s)...")
	# deterministically wait for MC to shutdown (SSH preferred, mcstatus fallback)
	try:
		confirmed = await asyncio.to_thread(wait_for_mc_shutdown, SHUTDOWN_MAX_WAIT, 5)
	except Exception:
		confirmed = False
	if not confirmed:
		# Conservative behavior: do NOT deallocate VM if we cannot confirm MC stopped
		try:
			await ctx.followup.send("⚠️ Không thể xác nhận Minecraft đã tắt trong giới hạn thời gian; VM sẽ KHÔNG bị deallocate. Vui lòng kiểm tra server hoặc dùng tùy chọn force nếu bạn muốn ép buộc deallocate.")
		except Exception:
			await ctx.send("⚠️ Không thể xác nhận Minecraft đã tắt trong giới hạn thời gian; VM sẽ KHÔNG bị deallocate. Vui lòng kiểm tra server hoặc dùng tùy chọn force nếu bạn muốn ép buộc deallocate.")
		return
	# If VM was already deallocated while we were attempting stop, skip azure stop
	if not compute_client or not vm_is_running():
		try:
			await ctx.followup.send("⚫ VM already deallocated or Azure not configured; skipping deallocate.")
		except Exception:
			await ctx.send("⚫ VM already deallocated or Azure not configured; skipping deallocate.")
		return
	if compute_client:
		loop = asyncio.get_running_loop()
		try:
			await ctx.followup.send("2️⃣ Đang tắt VM (deallocate)...")
		except Exception:
			await ctx.send("2️⃣ Đang tắt VM (deallocate)...")
		try:
			await loop.run_in_executor(None, azure_stop_vm)
			try:
				await ctx.followup.send("💤 Hệ thống đã tắt hoàn toàn.")
			except Exception:
				await ctx.send("💤 Hệ thống đã tắt hoàn toàn.")
		except Exception as e:
			try:
				await ctx.followup.send(f"Lỗi khi tắt VM: {e}")
			except Exception:
				await ctx.send(f"Lỗi khi tắt VM: {e}")
	else:
		try:
			await ctx.followup.send("Azure không được cấu hình; chỉ gửi lệnh stop đến MC.")
		except Exception:
			await ctx.send("Azure không được cấu hình; chỉ gửi lệnh stop đến MC.")
# Note: `stop` is provided as an explicit slash command via `stop_slash` below.


@commands.hybrid_command(name="restart_mc", description="Restart Minecraft server only")
async def restart_mc(ctx):
	"""Restart Minecraft only (assumes start script will relaunch)"""
	await ctx.defer()
	# Force restart: kill java process then start the server via startup script (requires SSH)
	if not vm_is_running():
		try:
			await ctx.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to restart.")
		except Exception:
			await ctx.send("⚫ **Azure VM:** already deallocated/offline — nothing to restart.")
		return
	try:
		await ctx.followup.send("🔄 Force restarting Minecraft server (killing JVM, then starting)...")
	except Exception:
		await ctx.send("🔄 Force restarting Minecraft server (killing JVM, then starting)...")
	# Prefer SSH for force kill+start
	if SSH_PASSWORD and SSH_HOST and SSH_USER:
		# kill any java process, wait, then start the server in a detached screen
		cmd = 'bash -lc "pkill -9 -f java || true; sleep 2; cd ~/minecraft && screen -dmS mc ./start.sh"'
		out = await asyncio.to_thread(ssh_command, cmd)
		try:
			await ctx.followup.send(f"✅ Force restart command executed: {str(out)[:1000]}")
		except Exception:
			await ctx.send(f"✅ Force restart command executed: {str(out)[:1000]}")
		return
	# If SSH not available, fall back to graceful RCON stop (best-effort)
	if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
		try:
			await asyncio.to_thread(rcon_command, 'stop')
			await asyncio.sleep(5)
			try:
				await ctx.followup.send("✅ Sent RCON stop (graceful). Note: server start requires SSH access to run the start script.")
			except Exception:
				await ctx.send("✅ Sent RCON stop (graceful). Note: server start requires SSH access to run the start script.")
			return
		except Exception as e:
			try:
				await ctx.followup.send(f"⚠️ RCON stop failed: {e} and SSH not configured — cannot force restart.")
			except Exception:
				await ctx.send(f"⚠️ RCON stop failed: {e} and SSH not configured — cannot force restart.")
			return
	# Nothing available to restart
	try:
		await ctx.followup.send("⚠️ Không thể thực hiện restart: SSH và RCON đều không được cấu hình.")
	except Exception:
		await ctx.send("⚠️ Không thể thực hiện restart: SSH và RCON đều không được cấu hình.")
# Note: `restart_mc` is provided as an explicit slash command via `restart_mc_slash` below.


# --- Explicit slash (tree) commands to ensure registration ---
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
		# Only attempt RCON if VM is running
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


@tree.command(name="start", description="Start Azure VM and Minecraft server")
async def start_slash(interaction: discord.Interaction):
	await interaction.response.defer()
	# record requester
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
	# ensure auto-shutdown checker is running after VM is started
	try:
		if not auto_shutdown_check.is_running():
			auto_shutdown_check.start()
	except Exception:
		pass
	await interaction.followup.send("2️⃣ Bật Minecraft server...")
	cmd = "cd ~/minecraft && screen -dmS mc ./start.sh"
	out = await asyncio.to_thread(ssh_command, cmd)
	await interaction.followup.send(f"✅ Lệnh khởi động đã gửi: {out[:1000]}")
	# Poll mcstatus every 5s until online or timeout, then send a short status message
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
			break
		await asyncio.sleep(5)
	if not server_online:
		await interaction.followup.send("⚠️ Máy chủ vẫn chưa online sau thời gian chờ; có thể server vẫn đang khởi động. Vui lòng kiểm tra lại sau.")


@tree.command(name="stop", description="Stop Minecraft server and deallocate VM")
async def stop_slash(interaction: discord.Interaction):
	await interaction.response.defer()
	await interaction.followup.send("🛑 Đang tắt server...")
	# short-circuit if VM not running
	if not vm_is_running():
		await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to stop.")
		return
	stopped = False
	if RCON_ENABLED and RCON_PKG_AVAILABLE and RCON_PASSWORD:
		try:
			out = await asyncio.wait_for(asyncio.to_thread(rcon_command, 'stop'), timeout=5)
			await interaction.followup.send(f"✅ Đã gửi lệnh stop via RCON: {str(out)[:1000]}")
			stopped = True
		except Exception as e:
			await interaction.followup.send(f"⚠️ RCON stop failed: {e}. Falling back to SSH...")
	if not stopped:
		try:
			out_ssh = await asyncio.to_thread(ssh_command, 'screen -S mc -p 0 -X stuff "stop^M"')
			if out_ssh == "SSH disabled: no SSH_PASSWORD configured":
				await interaction.followup.send("⚠️ SSH not configured; cannot send stop. If server is running, enable RCON or SSH.")
				return
		except Exception as e:
			await interaction.followup.send(f"Lỗi gửi lệnh stop qua SSH: {e}")
	await interaction.followup.send("⏳ Đang chờ Minecraft tắt (tối đa 60s)...")
	# deterministically wait for MC to shutdown (SSH preferred, mcstatus fallback)
	try:
		confirmed = await asyncio.to_thread(wait_for_mc_shutdown, SHUTDOWN_MAX_WAIT, 5)
	except Exception:
		confirmed = False
	if not confirmed:
		# Conservative behavior: do NOT deallocate VM if we cannot confirm MC stopped
		await interaction.followup.send("⚠️ Không thể xác nhận Minecraft đã tắt trong giới hạn thời gian; VM sẽ KHÔNG bị deallocate. Vui lòng kiểm tra server hoặc dùng tùy chọn force nếu bạn muốn ép buộc deallocate.")
		return
	# If VM became deallocated, skip deallocate
	if not compute_client or not vm_is_running():
		await interaction.followup.send("⚫ VM already deallocated or Azure not configured; skipping deallocate.")
		return
	loop = asyncio.get_running_loop()
	await interaction.followup.send("2️⃣ Đang tắt VM (deallocate)...")
	try:
		await loop.run_in_executor(None, azure_stop_vm)
		await interaction.followup.send("💤 Hệ thống đã tắt hoàn toàn.")
	except Exception as e:
		await interaction.followup.send(f"Lỗi khi tắt VM: {e}")


@tree.command(name="restart_mc", description="Restart Minecraft server only")
async def restart_mc_slash(interaction: discord.Interaction):
	await interaction.response.defer()
	# Force restart: prefer SSH kill+start, fallback to RCON stop (best-effort)
	if not vm_is_running():
		await interaction.followup.send("⚫ **Azure VM:** already deallocated/offline — nothing to restart.")
		return
	await interaction.followup.send("🔄 Force restarting Minecraft server (killing JVM, then starting)...")
	if SSH_PASSWORD and SSH_HOST and SSH_USER:
		cmd = 'bash -lc "pkill -9 -f java || true; sleep 2; cd ~/minecraft && screen -dmS mc ./start.sh"'
		out = await asyncio.to_thread(ssh_command, cmd)
		await interaction.followup.send(f"✅ Force restart command executed: {str(out)[:1000]}")
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


# --- Auto shutdown task ---
@tasks.loop(minutes=5)
async def auto_shutdown_check():
	"""If MC empty for several checks, stop MC and deallocate VM."""
	global EMPTY_CHECK_COUNT
	try:
		# if VM not running, stop this periodic check to avoid unnecessary work
		if not compute_client:
			return
		vm = compute_client.virtual_machines.get(AZURE_RESOURCE_GROUP, AZURE_VM_NAME, expand='instanceView')
		if "running" not in vm.instance_view.statuses[1].display_status.lower():
			EMPTY_CHECK_COUNT = 0
			# stop the loop until VM is started again
			try:
				auto_shutdown_check.stop()
			except Exception:
				pass
			return

		# check MC players: prefer RCON for exact count, fallback to mcstatus
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
			# Prefer the channel that requested start, else use AUTO_SHUTDOWN_CHANNEL_ID
			channel = None
			try:
				if LAST_REQUEST_CHANNEL_ID:
					channel = bot.get_channel(LAST_REQUEST_CHANNEL_ID)
			except Exception:
				channel = None
			if not channel and AUTO_SHUTDOWN_CHANNEL_ID:
				channel = bot.get_channel(AUTO_SHUTDOWN_CHANNEL_ID)
			if channel:
				await channel.send("⚠️ Không có ai chơi trong thời gian dài, Bot sẽ tắt máy để tiết kiệm chi phí.")
			# send stop then deterministically verify shutdown before deallocating
			await asyncio.to_thread(ssh_command, 'screen -S mc -p 0 -X stuff "stop^M"')
			try:
				confirmed = await asyncio.to_thread(wait_for_mc_shutdown, SHUTDOWN_MAX_WAIT, 5)
			except Exception:
				confirmed = False
			if confirmed:
				loop = asyncio.get_running_loop()
				await loop.run_in_executor(None, azure_stop_vm)
				if channel:
					await channel.send("💤 Đã tự động tắt máy thành công!")
			else:
				if channel:
					await channel.send("⚠️ Bot không thể xác nhận Minecraft đã tắt; VM sẽ không bị tắt tự động. Vui lòng kiểm tra server.")
			EMPTY_CHECK_COUNT = 0

	except Exception as e:
		logging.warning(f"auto_shutdown_check error: {e}")

# --- Admin: /wipe (hidden) ---
@tree.command(name="wipe", description="(Admin) Wipe Beanie's memory")
async def wipe(interaction: discord.Interaction):
	if not interaction.user.guild_permissions.administrator:
		await interaction.response.send_message("You need admin rights to use this.", ephemeral=True)
		return
	clear_memory()
	await interaction.response.send_message("Beanie's memory wiped!", ephemeral=True)
	print("Registered /wipe command")

if __name__ == "__main__":
	bot.run(DISCORD_TOKEN)
