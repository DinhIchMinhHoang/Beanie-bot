# --- ALL IMPORTS AT TOP ---
import os
from dotenv import load_dotenv
import logging
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button
import lyricsgenius
import yt_dlp
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
discord.FFmpegOpusAudio.executable = "./ffmpeg-8.0-essentials_build/bin/ffmpeg.exe"
genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel('models/gemini-2.5-flash')
genius = lyricsgenius.Genius(GENIUS_API_KEY, skip_non_songs=True, excluded_terms=["(Remix)", "(Live)"])



# --- Bot Setup (must be before any @tree.command or @bot.event) ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

class MusicControls(View):
	def __init__(self, queue, guild_id):
		super().__init__(timeout=None)
		self.queue = queue
		self.guild_id = guild_id

	@discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary)
	async def skip(self, interaction: discord.Interaction, button: Button):
		if self.queue.voice_client and self.queue.voice_client.is_playing():
			self.queue.voice_client.stop()
			await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
		else:
			await interaction.response.send_message("Nothing to skip.", ephemeral=True)

	@discord.ui.button(label="⏸️ Pause", style=discord.ButtonStyle.secondary)
	async def pause(self, interaction: discord.Interaction, button: Button):
		if self.queue.voice_client and self.queue.voice_client.is_playing():
			self.queue.voice_client.pause()
			await interaction.response.send_message("⏸️ Paused!", ephemeral=True)
		else:
			await interaction.response.send_message("Nothing is playing.", ephemeral=True)

	@discord.ui.button(label="▶️ Resume", style=discord.ButtonStyle.secondary)
	async def resume(self, interaction: discord.Interaction, button: Button):
		if self.queue.voice_client and self.queue.voice_client.is_paused():
			self.queue.voice_client.resume()
			await interaction.response.send_message("▶️ Resumed!", ephemeral=True)
		else:
			await interaction.response.send_message("Nothing is paused.", ephemeral=True)

	@discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
	async def stop(self, interaction: discord.Interaction, button: Button):
		if self.queue.voice_client:
			await self.queue.voice_client.disconnect()
		self.queue.clear()
		await interaction.response.send_message("⏹️ Stopped and cleared the queue.", ephemeral=True)


# --- Music Queue and Player ---
class Song:
	def __init__(self, url, title, artist, requester, thumbnail=None):
		self.url = url
		self.title = title
		self.artist = artist
		self.requester = requester
		self.thumbnail = thumbnail
		self.lyrics = None

class MusicQueue:
	def __init__(self):
		self.songs = []
		self.current = None
		self.is_playing = False
		self.voice_client = None
		self.text_channel = None
		self.now_playing_msg = None
		self.disconnect_task = None

	def add_song(self, song):
		self.songs.append(song)

	def next_song(self):
		if self.songs:
			self.current = self.songs.pop(0)
			return self.current
		self.current = None
		return None

	def clear(self):
		self.songs.clear()
		self.current = None

music_queues = {}  # guild_id: MusicQueue

def get_queue(guild_id):
	if guild_id not in music_queues:
		music_queues[guild_id] = MusicQueue()
	return music_queues[guild_id]

async def fetch_song_info(url_or_search, requester):
	ydl_opts = {
		'format': 'bestaudio/best',
		'noplaylist': True,
		'quiet': True,
		'default_search': 'ytsearch',
		'extract_flat': 'in_playlist',
	}
	with yt_dlp.YoutubeDL(ydl_opts) as ydl:
		info = ydl.extract_info(url_or_search, download=False)
		if 'entries' in info:
			info = info['entries'][0]
		title = info.get('title', 'Unknown')
		artist = info.get('uploader', 'Unknown')
		url = info.get('webpage_url', url_or_search)
		thumbnail = info.get('thumbnail')
		return Song(url, title, artist, requester, thumbnail)

async def fetch_lyrics(song):
	try:
		logging.info(f"[lyrics] Searching Genius for: title='{song.title}', artist='{song.artist}'")
		result = genius.search_song(song.title, song.artist)
		if result and result.lyrics:
			song.lyrics = result.lyrics
			return
		# Fallback: try searching by title only
		logging.info(f"[lyrics] Fallback: Searching Genius for title only: '{song.title}'")
		result = genius.search_song(song.title)
		if result and result.lyrics:
			song.lyrics = result.lyrics
		else:
			song.lyrics = None
	except Exception as e:
		logging.error(f"[lyrics] Error fetching lyrics: {e}")
		song.lyrics = None

def split_lyrics(lyrics):
	# Split lyrics into 1900-char chunks for Discord
	if not lyrics:
		return []
	return [lyrics[i:i+1900] for i in range(0, len(lyrics), 1900)]

async def send_queue_message(queue, channel, guild_id=None):
	if not queue.current:
		await channel.send("No song is currently playing.")
		return
	desc = f"**Now Playing:**\n{queue.current.title} by {queue.current.artist} (requested by {queue.current.requester})"
	if queue.songs:
		desc += "\n\n**Up Next:**"
		for idx, song in enumerate(queue.songs[:10], 1):
			desc += f"\n{idx}. {song.title} by {song.artist}"
		if len(queue.songs) > 10:
			desc += f"\n... and {len(queue.songs)-10} more track(s)"
	else:
		desc += "\n\nQueue is empty."
	view = MusicControls(queue, guild_id) if guild_id else None
	if queue.now_playing_msg:
		try:
			await queue.now_playing_msg.edit(content=desc, view=view)
		except Exception:
			queue.now_playing_msg = await channel.send(desc, view=view)
	else:
		queue.now_playing_msg = await channel.send(desc, view=view)

async def play_next(guild_id):
	queue = get_queue(guild_id)
	if not queue.songs:
		queue.is_playing = False
		queue.current = None
		if queue.voice_client:
			await queue.voice_client.disconnect()
		if queue.text_channel:
			await send_queue_message(queue, queue.text_channel, guild_id)
		return
	song = queue.next_song()
	queue.is_playing = True
	# Fetch lyrics in background
	asyncio.create_task(fetch_lyrics(song))
	# Play audio with error logging
	try:
		# Always use yt-dlp to get direct audio stream URL for playback
		ydl_opts = {
			'format': 'bestaudio/best',
			'noplaylist': True,
			'quiet': True,
			'default_search': 'ytsearch',
			'extract_flat': 'in_playlist',
		}
		logging.info(f"[play_next] Fetching audio for playback: {song.url}")
		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			info = ydl.extract_info(song.url, download=False)
			logging.info(f"[play_next] yt-dlp info (first pass): {info}")
			# If this is a playlist/search, get the first entry's video page URL
			if 'entries' in info:
				entry = info['entries'][0]
				video_url = entry.get('url')
				if not video_url.startswith('http'):
					video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
				logging.info(f"[play_next] Resolved video page URL: {video_url}")
				# Run yt-dlp again to get the direct stream URL
				info2 = ydl.extract_info(video_url, download=False)
				logging.info(f"[play_next] yt-dlp info (second pass): {info2}")
				stream_url = info2.get('url')
			else:
				# Direct video link
				stream_url = info.get('url')
		if not stream_url:
			raise Exception("No audio URL found in yt-dlp info.")
		logging.info(f"[play_next] FFmpeg input URL: {stream_url}")
		source = await discord.FFmpegOpusAudio.from_probe(
			stream_url,
			method='fallback',
			options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
		)
		queue.voice_client.play(
			source,
			after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), bot.loop)
		)
	except Exception as e:
		logging.error(f"[play_next] Error playing song: {e}")
		if queue.text_channel:
			await queue.text_channel.send(f"Error playing song: {e}")
		queue.is_playing = False
		if queue.voice_client:
			await queue.voice_client.disconnect()
		return
	# Post now playing and lyrics
	if queue.text_channel:
		await send_queue_message(queue, queue.text_channel, guild_id)
		# Wait for lyrics to be fetched
		await asyncio.sleep(2)
		if song.lyrics:
			for chunk in split_lyrics(song.lyrics):
				await queue.text_channel.send(chunk)
		else:
			await queue.text_channel.send("Lyrics not found.")

@tree.command(name="play", description="Play a song from YouTube (or add to queue)")
@app_commands.describe(query="YouTube URL or search term")
async def play(interaction: discord.Interaction, query: str):
	if not interaction.user.voice or not interaction.user.voice.channel:
		await interaction.response.send_message("You must be in a voice channel to use /play.", ephemeral=True)
		return
	queue = get_queue(interaction.guild.id)
	queue.text_channel = interaction.channel
	await interaction.response.defer()
	song = await fetch_song_info(query, interaction.user.display_name)
	queue.add_song(song)
	if not queue.is_playing:
		# Connect and play
		vc = await interaction.user.voice.channel.connect()
		queue.voice_client = vc
		await play_next(interaction.guild.id)
		await interaction.followup.send(f"Now playing: {song.title} by {song.artist}")
	else:
		await send_queue_message(queue, interaction.channel, interaction.guild.id)
		await interaction.followup.send(f"Added to queue: {song.title} by {song.artist}")

@tree.command(name="add", description="Add a song to the queue without playing")
@app_commands.describe(query="YouTube URL or search term")
async def add(interaction: discord.Interaction, query: str):
	queue = get_queue(interaction.guild.id)
	queue.text_channel = interaction.channel
	await interaction.response.defer()
	song = await fetch_song_info(query, interaction.user.display_name)
	queue.add_song(song)
	await send_queue_message(queue, interaction.channel, interaction.guild.id)
	await interaction.followup.send(f"Added to queue: {song.title} by {song.artist}")

@tree.command(name="queue", description="Show the current music queue")
async def show_queue(interaction: discord.Interaction):
	queue = get_queue(interaction.guild.id)
	await send_queue_message(queue, interaction.channel, interaction.guild.id)

@tree.command(name="stop", description="Stop music and disconnect")
async def stop(interaction: discord.Interaction):
	queue = get_queue(interaction.guild.id)
	if queue.voice_client:
		await queue.voice_client.disconnect()
	queue.clear()
	await interaction.response.send_message("Stopped and cleared the queue.")

# --- Auto-disconnect if alone ---
@bot.event
async def on_voice_state_update(member, before, after):
	if member.bot:
		return
	for guild_id, queue in music_queues.items():
		if queue.voice_client and queue.voice_client.channel:
			channel = queue.voice_client.channel
			if len([m for m in channel.members if not m.bot]) == 0:
				# No non-bot users left
				await asyncio.sleep(10)  # Wait 10 seconds before disconnect
				if len([m for m in channel.members if not m.bot]) == 0:
					await queue.voice_client.disconnect()
					queue.clear()
					if queue.text_channel:
						await queue.text_channel.send("No one left in voice, disconnecting.")


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

@tree.command(name="chat", description="Talk to Beanie (AI chat)")
@app_commands.describe(text="Your message to Beanie")
async def chat(interaction: discord.Interaction, text: str):
	global lockdown, lockdown_until
	if lockdown:
		await interaction.response.send_message("⏳ AI Chat is cooling down. Please wait.", ephemeral=True)
		return
	if not text.strip():
		await interaction.response.send_message("Please type something after /chat!", ephemeral=True)
		return

	# Echo the user's prompt publicly so others can see the question
	try:
		now_ts = datetime.now(VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S")
		if interaction.channel:
			await interaction.channel.send(f"**{interaction.user.display_name} asked (Hanoi time {now_ts}):**\n{text}")
	except Exception:
		pass

	await interaction.response.defer()
	# Add to queue: (interaction, text)
	await ai_queue.put((interaction, text))
	# Start processor if not running
	global ai_processing
	if not ai_processing:
		asyncio.create_task(process_ai_queue())
	print("Registered /chat command")


async def process_ai_queue():
	global ai_processing, lockdown, lockdown_until
	ai_processing = True
	while not ai_queue.empty():
		interaction, text = await ai_queue.get()
		add_to_memory(interaction.user.display_name, text)

		# Warning and Lockdown logic
		if len(chat_memory) == WARNING_THRESHOLD:
			await interaction.channel.send("⚠️ You have 3 messages left, make them worthy!")
		if len(chat_memory) >= MEMORY_LIMIT:
			lockdown = True
			now_vn = datetime.now(VIETNAM_TZ)
			lockdown_until = now_vn + timedelta(minutes=COOLDOWN_MINUTES)
			await interaction.channel.send("🔒 AI Chat is now locked for 1 hour! (Vietnam time)")
			try:
				await interaction.followup.send("AI Chat is now locked. Please wait for cooldown.")
			except Exception:
				pass
			continue

		# Prepare context for Gemini
		context = get_context()
		prompt = "\n".join(context[-20:])  # Only last 20 for efficiency
		prompt += f"\nBeanie:"

		try:
			response = await asyncio.to_thread(gemini.generate_content, prompt)
			reply = response.text.strip()
		except Exception as e:
			try:
				await interaction.followup.send(f"Error: {e}")
			except Exception:
				pass
			continue

		# Split and send in chunks
		chunks = [reply[i:i+CHUNK_SIZE] for i in range(0, len(reply), CHUNK_SIZE)]
		for chunk in chunks:
			try:
				await interaction.followup.send(chunk)
			except Exception:
				pass
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
