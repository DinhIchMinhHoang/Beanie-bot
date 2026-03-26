"""
AI Chat Feature Module for Beanie Bot
Handles AI conversation, memory management, and chat commands
"""

import asyncio
import logging
import gc
import os
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
import discord
import pytz

# Import rate limiting and validation
from core.rate_limiter import RateLimiter
from core.validation import Validator


class AIChatFeature(commands.Cog):
    def __init__(self, bot, gemini_client, config):
        self.bot = bot
        self.tree = bot.tree
        self.gemini_client = gemini_client
        self.config = config
        
        # Chat memory and state (per-guild)
        self.chat_memory = {}  # {guild_id: [messages]}
        self.lockdown = {}  # {guild_id: bool}
        self.lockdown_until = {}  # {guild_id: datetime}
        
        # AI processing (per-guild queues)
        self.ai_queues = {}  # {guild_id: Queue}
        self.ai_processing = {}  # {guild_id: bool}
        
        # Rate limiting: 10 messages per 60 seconds per user (guild-scoped)
        self.rate_limiter = RateLimiter(max_calls=10, period_seconds=60, name="ai_chat")
        
        # Start background tasks
        self.cooldown_check.start()
        asyncio.create_task(self.process_ai_queues())
    
    def get_guild_queue(self, guild_id: int):
        """Get or create AI queue for a guild."""
        if guild_id not in self.ai_queues:
            self.ai_queues[guild_id] = asyncio.Queue()
        return self.ai_queues[guild_id]
    
    def get_guild_memory(self, guild_id: int):
        """Get chat memory for a guild."""
        if guild_id not in self.chat_memory:
            self.chat_memory[guild_id] = []
        return self.chat_memory[guild_id]
    
    def get_context(self, guild_id: int):
        """Get chat context from memory for a specific guild."""
        memory = self.get_guild_memory(guild_id)
        return [f"{m['user']}: {m['content']}" for m in memory]

    def _get_storage(self):
        storage_getter = getattr(self.config, "get_storage", None)
        if not callable(storage_getter):
            return None
        storage = storage_getter()
        return storage if hasattr(storage, "append_chat_history") else None
    
    def add_to_memory(self, guild_id: int, user, content):
        """Add message to chat memory for a specific guild."""
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        memory = self.get_guild_memory(guild_id)
        memory.append({"user": user, "content": content, "time": now_vn})
        
        if len(memory) > self.config.MEMORY_LIMIT:
            memory.pop(0)
        
        storage = self._get_storage()
        if storage is not None:
            try:
                storage.append_chat_history(guild_id, user, content, self.config.MEMORY_LIMIT)
                return
            except Exception as e:
                logging.error(f"Failed to write chat history for guild {guild_id}: {e}")

        # Save chat history to guild-specific file (auto-trim)
        guild_config = self.config.get_guild_config(guild_id)
        try:
            if os.path.exists(guild_config.chat_history_file):
                with open(guild_config.chat_history_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            else:
                lines = []
            lines.append(f"[{datetime.now(pytz.UTC).isoformat()}] {user}: {content}\n")
            if len(lines) > self.config.MEMORY_LIMIT:
                lines = lines[-self.config.MEMORY_LIMIT:]
            with open(guild_config.chat_history_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            logging.error(f"Failed to write chat history for guild {guild_id}: {e}")
    
    def clear_memory(self, guild_id: int):
        """Clear chat memory for a specific guild."""
        if guild_id in self.chat_memory:
            self.chat_memory[guild_id] = []
        gc.collect()
    
    def check_lockdown(self, guild_id: int):
        """Check and update lockdown status for a specific guild."""
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        is_locked = self.lockdown.get(guild_id, False)
        lockdown_until = self.lockdown_until.get(guild_id)
        
        if is_locked and lockdown_until and now_vn >= lockdown_until:
            self.lockdown[guild_id] = False
            self.lockdown_until[guild_id] = None
            self.clear_memory(guild_id)
            return True
        return False
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle AI chat messages."""
        if message.author.bot:
            return
        if not message.guild:  # Ignore DMs
            return
        if not message.content.lower().startswith("/beanie"):
            return
        
        guild_id = message.guild.id
        user_id = message.author.id
        
        # Check rate limit
        allowed, wait_seconds = self.rate_limiter.is_allowed(user_id)
        if not allowed:
            await message.reply(f"⏱️ Rate limited. Please wait {wait_seconds:.0f} seconds.", delete_after=5)
            return
        
        # Check lockdown
        is_locked = self.lockdown.get(guild_id, False)
        if is_locked:
            await message.reply("⏳ AI Chat is cooling down. Please wait.")
            return
        
        # Extract and validate message text
        text = message.content[len("/beanie"):].strip()
        
        if not text:
            await message.reply("Please type something after /beanie!")
            return
        
        # Validate input: length and content safety
        is_valid, error_msg = Validator.validate_message(text, max_length=500)
        if not is_valid:
            await message.reply(f"❌ Invalid message: {error_msg}", delete_after=5)
            return
        
        # Safe to process
        queue = self.get_guild_queue(guild_id)
        await queue.put((message, text))
        
        if not self.ai_processing.get(guild_id, False):
            asyncio.create_task(self.process_guild_queue(guild_id))
    
    async def process_guild_queue(self, guild_id: int):
        """Process AI chat queue for a specific guild."""
        self.ai_processing[guild_id] = True
        queue = self.get_guild_queue(guild_id)
        memory = self.get_guild_memory(guild_id)
        
        while not queue.empty():
            message, text = await queue.get()
            self.add_to_memory(guild_id, message.author.display_name, text)
            
            if len(memory) == self.config.WARNING_THRESHOLD:
                await message.channel.send("⚠️ You have 3 messages left, make them worthy!")
            if len(memory) >= self.config.MEMORY_LIMIT:
                self.lockdown[guild_id] = True
                now_vn = datetime.now(self.config.VIETNAM_TZ)
                self.lockdown_until[guild_id] = now_vn + timedelta(minutes=self.config.COOLDOWN_MINUTES)
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
                context = self.get_context(guild_id)
                prompt = system_prompt + "\n" + "\n".join(context[-20:]) + f"\nBeanie:"
                
                try:
                    response = await asyncio.to_thread(
                        self.gemini_client.models.generate_content,
                        model='gemini-2.5-flash',
                        contents=prompt
                    )
                    reply = response.text.strip()
                except Exception as e:
                    await message.reply(f"Error: {e}")
                    continue
            
            chunks = [reply[i:i+self.config.CHUNK_SIZE] for i in range(0, len(reply), self.config.CHUNK_SIZE)]
            for chunk in chunks:
                await message.reply(chunk)
            self.add_to_memory(guild_id, "Beanie", reply)
            
            # Garbage collect after AI response
            gc.collect()
        
        self.ai_processing[guild_id] = False
    
    async def process_ai_queues(self):
        """Process all guild queues (legacy support)."""
        # This is called once at startup for background processing
        # Individual guilds will process their own queues via on_message
        pass
    
    @commands.hybrid_command(name="wipe", description="(Admin) Wipe Beanie's memory")
    async def wipe(self, ctx):
        """Wipe chat memory (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You need admin rights to use this.", ephemeral=True)
            return
        guild_id = ctx.guild.id
        self.clear_memory(guild_id)
        await ctx.send("Beanie's memory wiped!", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Register slash commands."""
        self.tree.add_command(
            app_commands.Command(
                name="wipe",
                description="(Admin) Wipe Beanie's memory",
                callback=self._wipe_slash
            )
        )
    
    async def _wipe_slash(self, interaction: discord.Interaction):
        """Slash command version of wipe."""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need admin rights to use this.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        self.clear_memory(guild_id)
        await interaction.response.send_message("Beanie's memory wiped!", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_cooldown_tick(self):
        """Called periodically to check cooldown."""
        if self.check_lockdown():
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    try:
                        await channel.send("🔔 AI Chat is available now!")
                    except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                        # Expected errors: channel deleted, no permission, etc.
                        continue
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout sending cooldown message to {channel.name}")
                        continue
                    except Exception as e:
                        logging.error(f"Unexpected error sending cooldown message: {e}")
                        continue
    
    @commands.Cog.listener()
    async def on_cog_load(self):
        """Called when cog is loaded."""
        logging.info("AI Chat feature loaded")
    
    def cog_unload(self):
        """Called when cog is unloaded."""
        self.cooldown_check.cancel()
    
    @tasks.loop(minutes=1)
    async def cooldown_check(self):
        """Background task to check cooldown for all guilds."""
        for guild in self.bot.guilds:
            if self.check_lockdown(guild.id):
                # Lockdown just ended for this guild
                for channel in guild.text_channels:
                    try:
                        await channel.send("🔔 AI Chat is available now!")
                        break  # Only send once per guild
                    except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                        # Expected errors: channel deleted, no permission, etc.
                        continue
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout sending cooldown message")
                        continue
                    except Exception as e:
                        logging.error(f"Error sending cooldown message: {e}")
                        continue


async def setup(bot):
    """Setup function for the AI Chat feature."""
    # This will be called by bot.load_extension()
    # The main.py should pass required dependencies
    pass
