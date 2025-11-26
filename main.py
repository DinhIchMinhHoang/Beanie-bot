# --- ALL IMPORTS AT TOP ---
import os
from dotenv import load_dotenv
import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button
## Removed music features: lyricsgenius, yt_dlp
import google.generativeai as genai
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

# --- External Service Setup ---
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel('models/gemini-2.5-flash')



# --- Bot Setup (must be before any @tree.command or @bot.event) ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree


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
			synced = await tree.sync()
			print(f"Synced {len(synced)} global commands.")
		except Exception as e:
			print(f"Sync error: {e}")
		cooldown_check.start()


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

		# Prepare context for Gemini
		context = get_context()
		prompt = "\n".join(context[-20:])  # Only last 20 for efficiency
		prompt += f"\nBeanie:"

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
