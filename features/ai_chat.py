"""
AI Chat Feature Module for Beanie Bot
Handles AI conversation via OpenCode API (OpenAI-compatible),
agent tool dispatch, memory management, and chat commands.
"""

import asyncio
import json
import logging
import gc
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
import discord
import pytz

from core.rate_limiter import RateLimiter
from core.validation import Validator
from features.agent import TOOL_DEFINITIONS, build_messages, dispatch_tool


class AIChatFeature(commands.Cog):
    def __init__(self, bot, openai_client, config, voice_feature=None, economy_feature=None):
        self.bot = bot
        self.tree = bot.tree
        self.openai_client = openai_client
        self.config = config
        self.voice_feature = voice_feature
        self.economy_feature = economy_feature

        self.chat_memory = {}
        self.lockdown = {}
        self.lockdown_until = {}

        self.ai_queues = {}
        self.ai_processing = {}

        self.rate_limiter = RateLimiter(max_calls=10, period_seconds=60, name="ai_chat")

        self.cooldown_check.start()
        asyncio.create_task(self.process_ai_queues())

    def get_guild_queue(self, guild_id: int):
        if guild_id not in self.ai_queues:
            self.ai_queues[guild_id] = asyncio.Queue()
        return self.ai_queues[guild_id]

    def get_guild_memory(self, guild_id: int):
        if guild_id not in self.chat_memory:
            self.chat_memory[guild_id] = []
        return self.chat_memory[guild_id]

    def get_context(self, guild_id: int):
        memory = self.get_guild_memory(guild_id)
        return [f"[{m['role']}] {m.get('content', '')}" for m in memory]

    def _get_storage(self):
        return self.config.get_storage()

    def add_to_memory(self, guild_id: int, role: str, content=None, tool_calls=None, tool_call_id=None, user_name=None):
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        memory = self.get_guild_memory(guild_id)
        entry = {"role": role, "time": now_vn}
        if content is not None:
            entry["content"] = content
        if tool_calls is not None:
            entry["tool_calls"] = tool_calls
        if tool_call_id is not None:
            entry["tool_call_id"] = tool_call_id
        if user_name is not None:
            entry["user"] = user_name
        memory.append(entry)

        if len(memory) > self.config.MEMORY_LIMIT:
            memory.pop(0)

        storage = self._get_storage()
        try:
            storage.append_chat_history(guild_id, role, json.dumps(entry, default=str), self.config.MEMORY_LIMIT)
        except Exception as e:
            logging.error(f"Failed to write chat history for guild {guild_id}: {e}")

    def clear_memory(self, guild_id: int):
        if guild_id in self.chat_memory:
            self.chat_memory[guild_id] = []
        gc.collect()

    def check_lockdown(self, guild_id: int):
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
        if message.author.bot:
            return
        if not message.guild:
            return
        if not message.content.lower().startswith("/beanie"):
            return

        guild_id = message.guild.id
        user_id = message.author.id

        allowed, wait_seconds = self.rate_limiter.is_allowed(user_id)
        if not allowed:
            await message.reply(f"⏱️ Rate limited. Please wait {wait_seconds:.0f} seconds.", delete_after=5)
            return

        is_locked = self.lockdown.get(guild_id, False)
        if is_locked:
            await message.reply("⏳ AI Chat is cooling down. Please wait.")
            return

        text = message.content[len("/beanie"):].strip()

        if not text:
            await message.reply("Please type something after /beanie!")
            return

        is_valid, error_msg = Validator.validate_message(text, max_length=500)
        if not is_valid:
            await message.reply(f"❌ Invalid message: {error_msg}", delete_after=5)
            return

        queue = self.get_guild_queue(guild_id)
        await queue.put((message, text))

        if not self.ai_processing.get(guild_id, False):
            asyncio.create_task(self.process_guild_queue(guild_id))

    async def process_guild_queue(self, guild_id: int):
        self.ai_processing[guild_id] = True
        queue = self.get_guild_queue(guild_id)
        memory = self.get_guild_memory(guild_id)

        while not queue.empty():
            message, text = await queue.get()
            self.add_to_memory(guild_id, "user", text, user_name=message.author.display_name)

            if len(memory) == self.config.WARNING_THRESHOLD:
                await message.channel.send("⚠️ You have 3 messages left, make them worthy!")
            if len(memory) >= self.config.MEMORY_LIMIT:
                self.lockdown[guild_id] = True
                now_vn = datetime.now(self.config.VIETNAM_TZ)
                self.lockdown_until[guild_id] = now_vn + timedelta(minutes=self.config.COOLDOWN_MINUTES)
                await message.channel.send("🔒 AI Chat is now locked for 1 hour! (Vietnam time)")
                continue

            async with message.channel.typing():
                try:
                    messages = build_messages(memory, text, max_context=60)

                    response = await self.openai_client.chat.completions.create(
                        model=self.config.OPENROUTER_MODEL,
                        messages=messages,
                        tools=TOOL_DEFINITIONS,
                        tool_choice="auto",
                    )

                    choice = response.choices[0]

                    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                        tool_calls_processed = []
                        for tool_call in choice.message.tool_calls:
                            tool_name = tool_call.function.name
                            try:
                                tool_args = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                tool_args = {}

                            ctx = {
                                "guild_id": guild_id,
                                "user_id": message.author.id,
                                "channel": message.channel,
                                "storage": self._get_storage(),
                                "config": self.config,
                                "voice_feature": self.voice_feature,
                                "economy_feature": self.economy_feature,
                                "minecraft_feature": self._get_minecraft_feature(),
                            }

                            result = await dispatch_tool(tool_name, tool_args, ctx)
                            tool_calls_processed.append({
                                "id": tool_call.id,
                                "name": tool_name,
                                "args": tool_args,
                                "result": result,
                            })

                        self.add_to_memory(
                            guild_id, "assistant", content=None,
                            tool_calls=[{"id": tc["id"], "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}} for tc in tool_calls_processed]
                        )

                        for tc in tool_calls_processed:
                            self.add_to_memory(guild_id, "tool", content=tc["result"], tool_call_id=tc["id"])

                        messages_with_results = build_messages(memory, text, max_context=60)

                        final_response = await self.openai_client.chat.completions.create(
                            model=self.config.OPENROUTER_MODEL,
                            messages=messages_with_results,
                        )

                        reply = final_response.choices[0].message.content or ""

                    else:
                        reply = choice.message.content or ""

                except Exception as e:
                    logging.error(f"AI API error for guild {guild_id}: {e}", exc_info=True)
                    await message.reply(f"❌ Lỗi xử lý: {e}")
                    continue

            if reply:
                chunks = [reply[i:i+self.config.CHUNK_SIZE] for i in range(0, len(reply), self.config.CHUNK_SIZE)]
                for chunk in chunks:
                    await message.reply(chunk)
                self.add_to_memory(guild_id, "assistant", reply)

            gc.collect()

        self.ai_processing[guild_id] = False

    def _get_minecraft_feature(self):
        for cog in self.bot.cogs.values():
            if cog.__class__.__name__ == "MinecraftFeature":
                return cog
        return None

    async def process_ai_queues(self):
        pass

    @commands.hybrid_command(name="wipe", description="(Admin) Wipe Beanie's memory")
    async def wipe(self, ctx):
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You need admin rights to use this.", ephemeral=True)
            return
        guild_id = ctx.guild.id
        self.clear_memory(guild_id)
        await ctx.send("Beanie's memory wiped!", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        self.tree.add_command(
            app_commands.Command(
                name="wipe",
                description="(Admin) Wipe Beanie's memory",
                callback=self._wipe_slash
            )
        )

    async def _wipe_slash(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need admin rights to use this.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        self.clear_memory(guild_id)
        await interaction.response.send_message("Beanie's memory wiped!", ephemeral=True)

    @commands.Cog.listener()
    async def on_cooldown_tick(self):
        pass

    @commands.Cog.listener()
    async def on_cog_load(self):
        logging.info("AI Chat feature loaded")

    def cog_unload(self):
        self.cooldown_check.cancel()

    @tasks.loop(minutes=1)
    async def cooldown_check(self):
        for guild in self.bot.guilds:
            if self.check_lockdown(guild.id):
                for channel in guild.text_channels:
                    try:
                        await channel.send("🔔 AI Chat is available now!")
                        break
                    except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                        continue
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout sending cooldown message")
                        continue
                    except Exception as e:
                        logging.error(f"Error sending cooldown message: {e}")
                        continue


async def setup(bot):
    pass
