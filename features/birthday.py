"""
Birthday Feature Module
Handles birthday management and automatic birthday notifications.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import gc
import random
from datetime import datetime

# Import validation and permission utilities
from core.validation import Validator
from core.permissions import admin_only


class BirthdayFeature(commands.Cog):
    """Feature for tracking and celebrating user birthdays."""
    
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.last_birthday_check = None  # Track last birthday check date
        
        # Start the birthday checking task
        self.birthday_check.start()
        logging.info("BirthdayFeature initialized")
    
    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        self.birthday_check.cancel()
    
    # ===========================
    # Data Management Methods
    # ===========================

    def _get_storage(self):
        return self.config.get_storage()
    
    def load_birthdays(self, guild_id: int):
        """Load birthdays from storage for specific guild."""
        storage = self._get_storage()
        return storage.load_birthdays(guild_id)
    
    def save_birthdays(self, guild_id: int, data):
        """Save birthdays to storage for specific guild."""
        storage = self._get_storage()
        storage.save_birthdays(guild_id, data)
    
    # ===========================
    # Background Tasks
    # ===========================
    
    @tasks.loop(hours=1)
    async def birthday_check(self):
        """Check birthdays at midnight (00:00) Hanoi time and send wishes."""
        await self.bot.wait_until_ready()
        now = datetime.now(self.config.VIETNAM_TZ)
        today = now.date()
        
        # Only run once per day - check if already processed today
        if self.last_birthday_check == today:
            return
        
        # Only process during hour 0 (midnight to 1 AM window)
        if now.hour != 0:
            return
        
        # Mark as processed for today
        self.last_birthday_check = today
        today_str = now.strftime("%d/%m")
        
        # Check birthdays for each guild
        for guild in self.bot.guilds:
            guild_config = self.config.get_guild_config(guild.id)
            birthday_channel_ids = guild_config.get_birthday_channel_ids()

            if not birthday_channel_ids:
                continue  # Skip if no birthday channel configured
            
            birthdays = self.load_birthdays(guild.id)
            
            # Find birthdays today
            for user_id, date_str in birthdays.items():
                if date_str == today_str:
                    try:
                        member = await self.bot.fetch_user(int(user_id))
                        name = member.display_name if member else f"<@{user_id}>"
                        wish = random.choice(self.config.BIRTHDAY_WISHES).format(name=name)
                    except Exception as e:
                        logging.error(f"Failed to build birthday wish in guild {guild.id}: {e}")
                        continue

                    # Send the wish to every configured birthday channel.
                    for channel_id in birthday_channel_ids:
                        channel = self.bot.get_channel(channel_id)
                        if not channel:
                            continue
                        try:
                            await channel.send(wish)
                        except Exception as e:
                            logging.error(
                                f"Failed to send birthday wish in guild {guild.id}, channel {channel_id}: {e}"
                            )
        
        gc.collect()
    
    # ===========================
    # Commands
    # ===========================
    
    @app_commands.command(name="birthday", description="Manage birthdays")
    @app_commands.describe(
        action="Action: add or list",
        user="User to add birthday for (required for 'add')",
        date="Birthday date in dd/mm format (required for 'add')"
    )
    async def birthday_cmd(self, interaction: discord.Interaction, action: str, user: discord.Member = None, date: str = None):
        """Birthday management (admin only)."""
        # Permission check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Admin only command.", ephemeral=True)
            return
        
        guild_id = interaction.guild.id
        
        # Validate action
        valid_actions = ["add", "list"]
        is_valid, normalized_action = Validator.validate_action(action, valid_actions)
        if not is_valid:
            await interaction.response.send_message(f"❌ Invalid action. Use: {', '.join(valid_actions)}", ephemeral=True)
            return
        
        if normalized_action == "add":
            # Validate required parameters for 'add'
            if not user or not date:
                await interaction.response.send_message("❌ Usage: /birthday add [user] [dd/mm]", ephemeral=True)
                return
            
            # Validate date format
            is_valid, normalized_date = Validator.validate_date_ddmm(date)
            if not is_valid:
                await interaction.response.send_message("❌ Invalid date! Use dd/mm format (e.g., 25/12)", ephemeral=True)
                return
            
            # Validate user ID
            is_valid, user_id = Validator.validate_user_id(user.id)
            if not is_valid:
                await interaction.response.send_message("❌ Invalid user.", ephemeral=True)
                return
            
            birthdays = self.load_birthdays(guild_id)
            birthdays[str(user_id)] = normalized_date
            self.save_birthdays(guild_id, birthdays)
            
            await interaction.response.send_message(f"✅ Birthday for {user.display_name} set to {normalized_date}!", ephemeral=True)
            gc.collect()
        
        elif normalized_action == "list":
            birthdays = self.load_birthdays(guild_id)
            if not birthdays:
                await interaction.response.send_message("📅 No birthdays registered yet.", ephemeral=True)
                return
            
            msg = "📅 **Registered Birthdays:**\n"
            for user_id, date_str in birthdays.items():
                try:
                    member = await interaction.client.fetch_user(int(user_id))
                    name = member.display_name if member else f"<@{user_id}>"
                except (discord.NotFound, discord.HTTPException):
                    logging.debug(f"User {user_id} not found when listing birthdays")
                    name = f"<@{user_id}>"
                except Exception as e:
                    logging.error(f"Error fetching user {user_id}: {e}")
                    name = f"<@{user_id}>"
                msg += f"• {name}: {date_str}\n"
            
            await interaction.response.send_message(msg, ephemeral=True)
            gc.collect()

    @app_commands.command(name="birthday_channel", description="Manage birthday announcement channels")
    @app_commands.describe(
        action="Action: set, add, remove, or list",
        channel="Text channel to use for birthday announcements"
    )
    @admin_only()
    async def birthday_channel_cmd(
        self,
        interaction: discord.Interaction,
        action: str,
        channel: discord.TextChannel = None,
    ):
        """Manage birthday announcement channels (admin only)."""
        # Explicit permission check (also applies when called via callback in tests)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ This command requires Administrator permission.",
                ephemeral=True
            )
            return
        
        guild_id = interaction.guild.id
        guild_config = self.config.get_guild_config(guild_id)
        
        # Validate action
        valid_actions = ["set", "add", "remove", "list"]
        is_valid, normalized_action = Validator.validate_action(action, valid_actions)
        if not is_valid:
            await interaction.response.send_message(
                f"❌ Invalid action. Use: {', '.join(valid_actions)}",
                ephemeral=True,
            )
            return

        if normalized_action == "list":
            channel_ids = guild_config.get_birthday_channel_ids()
            if not channel_ids:
                await interaction.response.send_message(
                    "📭 No birthday announcement channels configured yet.",
                    ephemeral=True,
                )
                return

            mentions = [f"<#{channel_id}>" for channel_id in channel_ids]
            await interaction.response.send_message(
                "🎂 Birthday announcement channels:\n" + "\n".join(f"• {m}" for m in mentions),
                ephemeral=True,
            )
            return

        if channel is None:
            await interaction.response.send_message(
                "❌ You must provide a text channel for this action.",
                ephemeral=True,
            )
            return

        # Validate channel format
        is_valid, channel_id = Validator.validate_channel_id(channel.id)
        if not is_valid:
            await interaction.response.send_message(
                "❌ Invalid channel.",
                ephemeral=True,
            )
            return

        if normalized_action == "set":
            guild_config.set_birthday_channel_ids([channel_id])
            await interaction.response.send_message(
                f"✅ Birthday channel set to {channel.mention}.",
                ephemeral=True,
            )
            return

        if normalized_action == "add":
            added = guild_config.add_birthday_channel_id(channel_id)
            if not added:
                await interaction.response.send_message(
                    f"⚠️ {channel.mention} is already in the birthday channel list.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"✅ Added {channel.mention} to birthday announcement channels.",
                ephemeral=True,
            )
            return

        if normalized_action == "remove":
            removed = guild_config.remove_birthday_channel_id(channel_id)
            if not removed:
                await interaction.response.send_message(
                    f"⚠️ {channel.mention} is not currently configured.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"✅ Removed {channel.mention} from birthday announcement channels.",
                ephemeral=True,
            )
            return


async def setup(bot):
    """Entry point for loading this cog."""
    from core.config import BotConfig
    await bot.add_cog(BirthdayFeature(bot, BotConfig))
