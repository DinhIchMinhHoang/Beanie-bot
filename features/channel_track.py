"""
Channel Voice Tracking Feature
Tracks total monthly voice time per tracked channel
"""

import asyncio
import logging
import re
import time
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands
import discord


class ChannelTrackingFeature(commands.Cog):
    def __init__(self, bot, config):
        self.bot = bot
        self.tree = bot.tree
        self.config = config
        
        # In-memory tracking: {channel_id: {"is_occupied": bool, "occupy_start_time": timestamp}}
        self.channel_occupancy = {}
        
        # Background tasks
        self.update_channel_names.start()
        self.monthly_reset_check.start()
        self.checkpoint_channel_stats.start()
    
    # --- Storage Helper ---
    
    def _get_storage(self):
        storage_getter = getattr(self.config, "get_storage", None)
        if not callable(storage_getter):
            return None
        storage = storage_getter()
        return storage if hasattr(storage, "load_tracked_channels") else None
    
    def _get_period_key(self):
        """Get current period key (YYYY-MM format)."""
        now = datetime.now(self.config.VIETNAM_TZ)
        return f"{now.year}-{str(now.month).zfill(2)}"
    
    def _get_channel_occupancy(self, channel_id):
        """Get current number of non-bot users in channel."""
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return 0
        # Count non-bot members
        return sum(1 for m in channel.members if not m.bot)
    
    # --- Event Listeners ---
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track channel-level voice uptime (0→1 and 1→0 transitions)."""
        guild_id = member.guild.id
        
        # Get storage
        storage = self._get_storage()
        if storage is None:
            return
        
        tracked = storage.load_tracked_channels(guild_id)
        tracked_set = set(tracked)
        
        channel_id_before = before.channel.id if before.channel else None
        channel_id_after = after.channel.id if after.channel else None
        
        # User left a tracked channel
        if channel_id_before and channel_id_before in tracked_set:
            occupancy = self._get_channel_occupancy(channel_id_before)
            # Channel just became empty (1→0)
            if occupancy == 0:
                if channel_id_before in self.channel_occupancy and self.channel_occupancy[channel_id_before]["is_occupied"]:
                    start_time = self.channel_occupancy[channel_id_before]["occupy_start_time"]
                    duration = time.time() - start_time
                    
                    # Record the uptime
                    period = self._get_period_key()
                    storage.add_to_channel_stats(guild_id, channel_id_before, period, duration)
                    
                    self.channel_occupancy[channel_id_before]["is_occupied"] = False
                    logging.info(f"Channel {channel_id_before} became empty. Recorded {duration:.0f}s uptime")
        
        # User joined a tracked channel
        if channel_id_after and channel_id_after in tracked_set:
            occupancy = self._get_channel_occupancy(channel_id_after)
            # Channel just became occupied (0→1)
            if occupancy == 1:  # Now has exactly 1 person (this member)
                if channel_id_after not in self.channel_occupancy:
                    self.channel_occupancy[channel_id_after] = {}
                
                self.channel_occupancy[channel_id_after]["is_occupied"] = True
                self.channel_occupancy[channel_id_after]["occupy_start_time"] = time.time()
                logging.info(f"Channel {channel_id_after} became occupied at {self.channel_occupancy[channel_id_after]['occupy_start_time']}")
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Clean up tracking for deleted channels."""
        if not isinstance(channel, discord.VoiceChannel):
            return
        
        guild_id = channel.guild.id
        channel_id = channel.id
        
        storage = self._get_storage()
        if storage is None:
            return
        
        # Remove from tracking
        storage.remove_tracked_channel(guild_id, channel_id)
        
        # Clean up RAM
        if channel_id in self.channel_occupancy:
            del self.channel_occupancy[channel_id]
        
        logging.info(f"Cleaned up tracking for deleted channel {channel_id} in guild {guild_id}")
    
    # --- Background Tasks ---
    
    @tasks.loop(minutes=5)
    async def update_channel_names(self):
        """Update tracked channel names with current stats."""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                storage = self._get_storage()
                if storage is None:
                    continue
                
                tracked = storage.load_tracked_channels(guild_id)
                period = self._get_period_key()
                
                for channel_id in tracked:
                    try:
                        channel = self.bot.get_channel(channel_id)
                        if not channel or not isinstance(channel, discord.VoiceChannel):
                            continue
                        
                        # Get stats
                        total_seconds = storage.load_channel_voice_stats(guild_id, channel_id, period)
                        total_hours = int(total_seconds / 3600)
                        
                        # Get current name and strip old suffix
                        current_name = channel.name
                        clean_name = re.sub(r'・\d+h$', '', current_name).strip()
                        
                        # Build new name
                        new_name = f"{clean_name}・{total_hours}h"
                        
                        # Update if changed
                        if new_name != current_name:
                            await channel.edit(name=new_name)
                            logging.info(f"Updated channel {channel_id} name to: {new_name}")
                        
                        # Rate limit: 1 edit per 5.5 seconds
                        await asyncio.sleep(5.5)
                    
                    except Exception as e:
                        logging.error(f"Failed to update channel {channel_id}: {e}")
            
            except Exception as e:
                logging.error(f"Channel name update error for guild {guild_id}: {e}")
    
    @tasks.loop(hours=1)
    async def checkpoint_channel_stats(self):
        """Checkpoint in-progress occupancy to DB (for period boundaries)."""
        await self.bot.wait_until_ready()
        
        storage = self._get_storage()
        if storage is None:
            return
        
        now = time.time()
        period = self._get_period_key()
        
        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                tracked = storage.load_tracked_channels(guild_id)
                
                for channel_id in tracked:
                    if channel_id in self.channel_occupancy:
                        occupancy_state = self.channel_occupancy[channel_id]
                        # If channel is currently occupied, save the in-progress time
                        if occupancy_state.get("is_occupied"):
                            start_time = occupancy_state.get("occupy_start_time")
                            if start_time:
                                duration = now - start_time
                                storage.add_to_channel_stats(guild_id, channel_id, period, duration)
                                # Reset timer for next checkpoint
                                occupancy_state["occupy_start_time"] = now
                                logging.info(f"Checkpointed in-progress occupancy for channel {channel_id}: {duration:.0f}s")
            
            except Exception as e:
                logging.error(f"Checkpoint error for guild {guild_id}: {e}")
    
    @tasks.loop(minutes=5)
    async def monthly_reset_check(self):
        """Check if monthly reset is needed and archive/reset stats."""
        await self.bot.wait_until_ready()
        
        now = datetime.now(self.config.VIETNAM_TZ)
        current_month = now.month
        
        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                
                storage = self._get_storage()
                if storage is None:
                    continue
                
                # Check if reset needed
                state = storage.load_state(guild_id)
                last_reset_month = state.get("last_channel_reset_month")
                
                if last_reset_month is None:
                    state["last_channel_reset_month"] = current_month
                    storage.save_state(guild_id, state)
                    continue
                
                if last_reset_month == current_month:
                    continue
                
                # Monthly reset triggered
                logging.info(f"Channel monthly reset for guild {guild_id}, month {current_month}")
                
                # 1. Checkpoint first
                await self.checkpoint_channel_stats()
                
                # 2. Get tracked channels and archive their stats
                tracked = storage.load_tracked_channels(guild_id)
                prev_period = f"{now.year}-{str(now.month - 1).zfill(2)}" if now.month > 1 else f"{now.year - 1}-12"
                
                for channel_id in tracked:
                    total_seconds = storage.load_channel_voice_stats(guild_id, channel_id, prev_period)
                    if total_seconds > 0:
                        storage.archive_channel_stats(
                            guild_id, now.year if now.month > 1 else now.year - 1,
                            now.month - 1 if now.month > 1 else 12,
                            channel_id, total_seconds
                        )
                
                # 3. Reset current stats
                storage.reset_channel_stats_for_period(guild_id, prev_period)
                
                # 4. Update state
                state["last_channel_reset_month"] = current_month
                storage.save_state(guild_id, state)
                
                logging.info(f"Channel stats reset for guild {guild_id}")
            
            except Exception as e:
                logging.error(f"Monthly reset error for guild {guild_id}: {e}")
    
    # --- Commands ---
    
    channel = app_commands.Group(name="channel", description="Manage tracked voice channels")
    
    @channel.command(name="add", description="Start tracking a voice channel")
    @app_commands.describe(channel_id="Discord voice channel ID")
    async def channel_add(self, interaction: discord.Interaction, channel_id: str):
        """Add a voice channel to tracking."""
        try:
            ch_id = int(channel_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid channel ID", ephemeral=True)
            return
        
        guild_id = interaction.guild_id
        storage = self._get_storage()
        if storage is None:
            await interaction.response.send_message("❌ Storage unavailable", ephemeral=True)
            return
        
        # Verify channel exists and is voice
        channel = self.bot.get_channel(ch_id)
        if not channel or not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message("❌ Channel not found or not a voice channel", ephemeral=True)
            return
        
        # Check if already tracked
        tracked = storage.load_tracked_channels(guild_id)
        if ch_id in tracked:
            await interaction.response.send_message(f"⚠️ Channel {channel.name} is already tracked", ephemeral=True)
            return
        
        # Add to tracking
        storage.add_tracked_channel(guild_id, ch_id)
        
        await interaction.response.send_message(
            f"✅ Started tracking **{channel.name}**\n`{ch_id}`",
            ephemeral=True
        )
    
    @channel.command(name="remove", description="Stop tracking a voice channel")
    @app_commands.describe(channel_id="Discord voice channel ID")
    async def channel_remove(self, interaction: discord.Interaction, channel_id: str):
        """Remove a voice channel from tracking."""
        try:
            ch_id = int(channel_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid channel ID", ephemeral=True)
            return
        
        guild_id = interaction.guild_id
        storage = self._get_storage()
        if storage is None:
            await interaction.response.send_message("❌ Storage unavailable", ephemeral=True)
            return
        
        # Check if tracked
        tracked = storage.load_tracked_channels(guild_id)
        if ch_id not in tracked:
            await interaction.response.send_message("❌ Channel not in tracking", ephemeral=True)
            return
        
        # Get channel name
        channel = self.bot.get_channel(ch_id)
        ch_name = channel.name if channel else f"Channel {ch_id}"
        
        # Remove from tracking
        storage.remove_tracked_channel(guild_id, ch_id)
        
        # Clean up RAM
        if ch_id in self.channel_occupancy:
            del self.channel_occupancy[ch_id]
        
        await interaction.response.send_message(
            f"✅ Stopped tracking **{ch_name}**",
            ephemeral=True
        )
    
    @channel.command(name="list", description="View all tracked voice channels with all-time totals")
    async def channel_list(self, interaction: discord.Interaction):
        """List all tracked channels with their all-time stats."""
        guild_id = interaction.guild_id
        storage = self._get_storage()
        if storage is None:
            await interaction.response.send_message("❌ Storage unavailable", ephemeral=True)
            return
        
        tracked = storage.load_tracked_channels(guild_id)
        
        if not tracked:
            await interaction.response.send_message("📭 No channels are being tracked yet", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📊 Tracked Voice Channels (All-Time)",
            color=discord.Color.blue()
        )
        
        for ch_id in tracked:
            channel = self.bot.get_channel(ch_id)
            ch_name = channel.name if channel else f"Channel {ch_id}"
            
            total_seconds = storage.load_all_time_channel_stats(guild_id, ch_id)
            hours = int(total_seconds / 3600)
            minutes = int((total_seconds % 3600) / 60)
            
            embed.add_field(
                name=f"🎤 {ch_name}",
                value=f"{hours}h {minutes}m",
                inline=False
            )
        
        now = datetime.now(self.config.VIETNAM_TZ)
        embed.set_footer(text=f"Updated at {now.strftime('%d/%m/%Y %H:%M')} (Vietnam Time)")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @channel.command(name="edit", description="(Admin) Manually edit channel stats")
    @app_commands.describe(
        channel_id="Discord voice channel ID",
        hours="Total hours to set for this month"
    )
    async def channel_edit(self, interaction: discord.Interaction, channel_id: str, hours: float):
        """Manually edit channel stats (admin only)."""
        # Admin check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permission required", ephemeral=True)
            return
        
        try:
            ch_id = int(channel_id)
        except ValueError:
            await interaction.response.send_message("❌ Invalid channel ID", ephemeral=True)
            return
        
        if hours < 0:
            await interaction.response.send_message("❌ Hours cannot be negative", ephemeral=True)
            return
        
        guild_id = interaction.guild_id
        storage = self._get_storage()
        if storage is None:
            await interaction.response.send_message("❌ Storage unavailable", ephemeral=True)
            return
        
        # Check if tracked
        tracked = storage.load_tracked_channels(guild_id)
        if ch_id not in tracked:
            await interaction.response.send_message("❌ Channel not in tracking", ephemeral=True)
            return
        
        # Convert hours to seconds
        total_seconds = hours * 3600
        period = self._get_period_key()
        
        # Update stats
        storage.save_channel_voice_stats(guild_id, ch_id, period, total_seconds)
        
        # Get channel name
        channel = self.bot.get_channel(ch_id)
        ch_name = channel.name if channel else f"Channel {ch_id}"
        
        await interaction.response.send_message(
            f"✅ Updated **{ch_name}** to **{hours}h** for {period}",
            ephemeral=True
        )
    
    # --- Cog Lifecycle ---
    
    def cog_unload(self):
        """Clean up on unload."""
        self.update_channel_names.cancel()
        self.monthly_reset_check.cancel()
        self.checkpoint_channel_stats.cancel()


async def setup(bot):
    """Setup function for the Channel Tracking feature."""
    pass
