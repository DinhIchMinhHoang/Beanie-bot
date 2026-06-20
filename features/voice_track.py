"""
Voice Tracking Feature Module for Beanie Bot
Handles voice stats, rankings, entrance sounds, and leaderboards
"""

import asyncio
import logging
import gc
import os
import json
import time
import random
from datetime import datetime
from discord.ext import commands, tasks
from discord import app_commands
import discord
from gtts import gTTS

# Import permission utilities
from core.permissions import admin_only


class VoiceTrackingFeature(commands.Cog):
    def __init__(self, bot, ffmpeg_exec, config):
        self.bot = bot
        self.tree = bot.tree
        self.ffmpeg_exec = ffmpeg_exec
        self.config = config
        
        # Voice tracking state
        self.voice_join_times = {}  # {guild_id: {user_id: start_timestamp}} - only in RAM
        self.leaderboard_updating = set()  # {guild_id} - track which guilds are currently updating leaderboards
        self.leaderboard_update_times = {}  # {guild_id: start_time} - for timeout detection
        
        # Audio infrastructure
        self.audio_lock = asyncio.Lock()
        self.say_queue = asyncio.Queue(maxsize=10)
        self.say_cooldowns = {}  # {user_id: timestamp}
        
        # Start background tasks
        self.update_leaderboard.start()
        self.monthly_reset_check.start()
        self.periodic_role_sync.start()
        self.voice_checkpoint.start()
        
        # Start say queue processor
        asyncio.create_task(self.process_say_queue())
    
    # --- Data Management Functions ---

    def _get_storage(self):
        storage_getter = getattr(self.config, "get_storage", None)
        if not callable(storage_getter):
            return None
        storage = storage_getter()
        return storage if hasattr(storage, "load_voice_stats") else None
    
    def load_voice_stats(self, guild_id: int):
        """Lazy load voice stats from JSON file for specific guild. Auto-migrates old format."""
        storage = self._get_storage()
        if storage is not None:
            stats = storage.load_voice_stats(guild_id)
            # Safety check: verify guild_id is being filtered correctly in storage layer
            logging.debug(f"Loaded {len(stats)} voice stat entries from storage for guild {guild_id}")
            return stats

        guild_config = self.config.get_guild_config(guild_id)
        if not os.path.exists(guild_config.voice_stats_file):
            logging.info(f"voice stats file not found: {guild_config.voice_stats_file}")
            return {}
        try:
            size = os.path.getsize(guild_config.voice_stats_file)
            logging.info(f"Loading voice stats from {guild_config.voice_stats_file} (size={size} bytes)")
        except Exception as e:
            logging.warning(f"Could not stat {guild_config.voice_stats_file}: {e}")
        try:
            with open(guild_config.voice_stats_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load {guild_config.voice_stats_file}: {e}")
            return {}
        
        # Auto-migrate old format to new format
        migrated = {}
        try:
            for user_id, value in data.items():
                if isinstance(value, dict) and "total" in value:
                    migrated[user_id] = value["total"]
                elif isinstance(value, (int, float)):
                    migrated[user_id] = value
                else:
                    migrated[user_id] = 0
        except Exception as e:
            logging.error(f"Error migrating voice stats structure: {e}")
            return {}
        return migrated
    
    def validate_and_clean_voice_stats(self, guild_id: int):
        """
        Safety check: Remove voice stats entries for users who aren't competitors.
        This prevents cross-guild user data contamination.
        """
        try:
            stats = self.load_voice_stats(guild_id)
            competitors = self.load_competitors(guild_id)
            competitors_set = set(competitors.keys())
            
            # Find users in stats that aren't competitors
            extra_users = set(stats.keys()) - competitors_set
            
            if extra_users:
                logging.warning(
                    f"Found {len(extra_users)} non-competitor users in voice stats for guild {guild_id}: "
                    f"{extra_users}. Removing them to prevent cross-guild contamination."
                )
                # Remove non-competitors from stats
                cleaned_stats = {uid: stats[uid] for uid in competitors_set if uid in stats}
                self.save_voice_stats(guild_id, cleaned_stats)
                return True
            return False
        except Exception as e:
            logging.error(f"Failed to validate voice stats for guild {guild_id}: {e}")
            return False
    
    def save_voice_stats(self, guild_id: int, data):
        """Save voice stats to JSON file atomically for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            storage.save_voice_stats(guild_id, data)
            return

        guild_config = self.config.get_guild_config(guild_id)
        try:
            tmp = guild_config.voice_stats_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, guild_config.voice_stats_file)
        except Exception as e:
            logging.error(f"Failed to save voice stats atomically for guild {guild_id}: {e}")
    
    def load_all_time_stats(self, guild_id: int):
        """Load cumulative voice stats across current and all archive files."""
        storage = self._get_storage()
        if storage is not None:
            return storage.load_all_time_voice_stats(guild_id)

        totals = {}
        # Start with current stats
        try:
            current = self.load_voice_stats(guild_id)
            for uid, secs in current.items():
                totals[uid] = totals.get(uid, 0) + int(secs or 0)
        except Exception as e:
            logging.warning(f"Failed to load current voice stats for all-time aggregation: {e}")
        
        # Include archive files
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
    
    def load_previous_month_archived_stats(self, guild_id: int):
        """Load the previous month's archived stats for hall of fame display."""
        storage = self._get_storage()
        if storage is not None:
            # Try to load from SQLite archive
            now = datetime.now(self.config.VIETNAM_TZ)
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            
            try:
                # Try to get from archive table
                archived = storage.load_voice_stats_archive(guild_id, prev_year, prev_month)
                if archived:
                    logging.info(f"Loaded archived stats from SQLite for {prev_year}-{prev_month:02d}")
                    return archived
            except Exception as e:
                logging.warning(f"Failed to load from SQLite archive: {e}")
        
        # Fallback: try to load from legacy JSON archive file
        guild_config = self.config.get_guild_config(guild_id)
        now = datetime.now(self.config.VIETNAM_TZ)
        prev_month = now.month - 1 if now.month > 1 else 12
        prev_year = now.year if now.month > 1 else now.year - 1
        
        archive_file = guild_config.get_file_path(f"archive_{prev_year}_{str(prev_month).zfill(2)}.json")
        try:
            if os.path.exists(archive_file):
                with open(archive_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logging.info(f"Loaded archived stats from {archive_file}")
                return data
        except Exception as e:
            logging.warning(f"Failed to load archive from {archive_file}: {e}")
        
        logging.warning(f"No archived stats found for {prev_year}-{prev_month:02d}")
        return {}
    
    
    def load_competitors(self, guild_id: int):
        """Lazy load competitors dict from JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            return storage.load_competitors(guild_id)

        guild_config = self.config.get_guild_config(guild_id)
        if not os.path.exists(guild_config.competitors_file):
            return {}
        try:
            with open(guild_config.competitors_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Handle migration from list to dict
                if isinstance(data, list):
                    return {str(uid): None for uid in data}
                return data
        except Exception:
            return {}
    
    def save_competitors(self, guild_id: int, data):
        """Save competitors dict to JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            storage.save_competitors(guild_id, data)
            return

        guild_config = self.config.get_guild_config(guild_id)
        try:
            with open(guild_config.competitors_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Failed to save competitors for guild {guild_id}: {e}")
    
    def load_entry_settings(self, guild_id: int):
        """Lazy load entry settings from JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            return storage.load_entry_settings(guild_id)

        guild_config = self.config.get_guild_config(guild_id)
        if not os.path.exists(guild_config.entry_settings_file):
            return {}
        try:
            with open(guild_config.entry_settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    def save_entry_settings(self, guild_id: int, data):
        """Save entry settings to JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            storage.save_entry_settings(guild_id, data)
            return

        guild_config = self.config.get_guild_config(guild_id)
        try:
            with open(guild_config.entry_settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Failed to save entry settings for guild {guild_id}: {e}")
    
    def load_state(self, guild_id: int):
        """Lazy load state from JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            return storage.load_state(guild_id)

        guild_config = self.config.get_guild_config(guild_id)
        if not os.path.exists(guild_config.state_file):
            return {}
        try:
            with open(guild_config.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    def save_state(self, guild_id: int, data):
        """Save state to JSON file for specific guild."""
        storage = self._get_storage()
        if storage is not None:
            storage.save_state(guild_id, data)
            return

        guild_config = self.config.get_guild_config(guild_id)
        try:
            with open(guild_config.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Failed to save state for guild {guild_id}: {e}")
    
    def get_user_rank(self, total_hours):
        """Get rank name, perks, role ID, and coin multiplier based on total hours."""
        if total_hours >= 160:
            return ("Legendary", 1475814299120435301, ["/say", "/entry on/off", "/entry add - Custom TTS/File"], 4.0)
        elif total_hours >= 140:
            return ("Immortal", 1475813978201653330, ["/say", "/entry on/off", "/entry add - Custom TTS/File"], 3.5)
        elif total_hours >= 120:
            return ("Elite", 1475813832411709461, ["/say", "/entry on/off", 'Default Entrance: "Xin chào {name}"'], 3.0)
        elif total_hours >= 100:
            return ("Diamond", 1475808953681051738, ["/say", "/entry on/off", 'Default Entrance: "Xin chào {name}"'], 2.6)
        elif total_hours >= 80:
            return ("Platinum", 1475809119049875528, ["/say"], 2.2)
        elif total_hours >= 60:
            return ("Gold", 1475808898370769018, ["/say"], 1.8)
        elif total_hours >= 40:
            return ("Silver", 1475808847649181778, [], 1.5)
        elif total_hours >= 20:
            return ("Bronze", 1475808729705353290, [], 1.2)
        else:
            return ("Iron", 1475819335514849391, [], 1.0)

    def get_rank_role_id_for_guild(self, guild_id: int, rank_name: str):
        """Get role ID for a rank name using guild-specific configured role IDs."""
        rank_order = [
            "Iron",
            "Bronze",
            "Silver",
            "Gold",
            "Platinum",
            "Diamond",
            "Elite",
            "Immortal",
            "Legendary",
        ]

        guild_config = self.config.get_guild_config(guild_id)
        role_ids = guild_config.get_rank_role_ids() or []

        if rank_name not in rank_order:
            return None

        idx = rank_order.index(rank_name)
        if idx >= len(role_ids):
            return None

        return role_ids[idx]
    
    def checkpoint_voice_stats(self, guild_id: int):
        """Checkpoint voice stats for users currently in voice channels for a specific guild."""
        now = time.time()
        guild_times = self.voice_join_times.get(guild_id)
        if not guild_times:
            return
        
        stats = self.load_voice_stats(guild_id)
        for user_id, join_time in list(guild_times.items()):
            duration = now - join_time
            if user_id not in stats:
                stats[user_id] = 0
            stats[user_id] += duration
            guild_times[user_id] = now  # Reset to current time

            # Economy: earn coins for time spent in voice
            total_hours = stats[user_id] / 3600
            _, _, _, mult = self.get_user_rank(total_hours)
            coins_earned = (duration / 600) * mult  # 1 base coin per 10 min
            storage = self._get_storage()
            if storage:
                storage.add_coins(guild_id, int(user_id), coins_earned)
        
        self.save_voice_stats(guild_id, stats)
        gc.collect()
    
    async def apply_rank_roles_to_guild(self, guild: discord.Guild):
        """Apply rank roles to all members in a guild based on voice_stats.json."""
        guild_id = guild.id
        guild_config = self.config.get_guild_config(guild_id)
        
        stats = self.load_voice_stats(guild_id)
        competitors = self.load_competitors(guild_id)
        competitors_set = set(competitors.keys())
        
        # Get rank role IDs for this guild
        rank_role_ids = guild_config.get_rank_role_ids()
        role_map = {rid: guild.get_role(rid) for rid in rank_role_ids}
        
        for member in guild.members:
            try:
                user_id = str(member.id)
                current_rank_roles = [r for r in member.roles if r.id in rank_role_ids]
                
                # If not a competitor, remove any rank roles
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
                rank_name, _, _, _ = self.get_user_rank(total_hours)
                role_id = self.get_rank_role_id_for_guild(guild_id, rank_name)
                if role_id is None:
                    logging.warning(
                        f"No configured role ID for rank {rank_name} in guild {guild.id}"
                    )
                    continue
                
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
                
                # Remove any other rank roles
                to_remove = [r for r in current_rank_roles if r.id != role_id]
                if to_remove:
                    try:
                        await member.remove_roles(*to_remove, reason="Rank sync: remove old roles")
                    except Exception as e:
                        logging.warning(f"Failed to remove old rank roles for {member.id}: {e}")
                
                # Small sleep to avoid rate limits
                await asyncio.sleep(0.15)
            
            except Exception as e:
                logging.error(f"Error applying rank for member {member.id}: {e}")
    
    # --- Background Tasks ---
    
    @tasks.loop(hours=1)
    async def periodic_role_sync(self):
        """Periodically sync rank roles across all guilds."""
        await self.bot.wait_until_ready()
        try:
            for guild in self.bot.guilds:
                await self.apply_rank_roles_to_guild(guild)
        except Exception as e:
            logging.error(f"Periodic role sync error: {e}")
    
    @tasks.loop(hours=1)
    async def update_leaderboard(self):
        """Update voice channel names hourly using current-month stats."""
        await self.bot.wait_until_ready()
        
        guild_list = list(self.bot.guilds)
        # Process guilds sequentially to avoid global rate limits
        for guild_idx, guild in enumerate(guild_list):
            try:
                guild_id = guild.id
                
                # Skip if already updating this guild's leaderboard (prevents concurrent updates)
                if guild_id in self.leaderboard_updating:
                    start_time = self.leaderboard_update_times.get(guild_id, 0)
                    if time.time() - start_time < 600:  # 10 minute timeout
                        logging.info(f"Leaderboard update already in progress for guild {guild_id}, skipping...")
                        continue
                    else:
                        logging.warning(f"Leaderboard update for guild {guild_id} stale (>10min), resetting...")
                        self.leaderboard_updating.discard(guild_id)
                
                self.leaderboard_updating.add(guild_id)
                self.leaderboard_update_times[guild_id] = time.time()
                logging.info(f"Starting leaderboard update for guild {guild_id}")
                
                # Validate and clean voice stats (remove non-competitors to prevent contamination)
                if self.validate_and_clean_voice_stats(guild_id):
                    logging.info(f"Cleaned contaminated voice stats for guild {guild_id}")
                
                # Checkpoint: Save current voice stats for people in voice channels
                self.checkpoint_voice_stats(guild_id)
                
                competitors = self.load_competitors(guild_id)
                if not competitors:
                    self.leaderboard_updating.discard(guild_id)
                    continue
                
                # Use current-month totals for leaderboard channel names.
                stats = self.load_voice_stats(guild_id)
                logging.info(f"Leaderboard update for guild {guild_id} - loaded current-month stats sample: {dict(list(stats.items())[:10])}")
                
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
                        channel = self.bot.get_channel(int(channel_id))
                        if not channel:
                            continue
                        
                        try:
                            # Use guild member for guild-specific display name (not global user)
                            guild_member = guild.get_member(int(user_id))
                            name = guild_member.display_name if guild_member else f"User{user_id}"
                        except (discord.NotFound, discord.HTTPException) as e:
                            logging.warning(f"Failed to fetch user {user_id} for leaderboard: {e}")
                            name = f"User{user_id}"
                        except Exception as e:
                            logging.error(f"Unexpected error fetching user {user_id}: {e}")
                            name = f"User{user_id}"
                        
                        if i < len(medals):
                            medal = medals[i]
                        else:
                            medal = f"#{i+1}"
                        new_name = f"{medal} {name}: {int(hours)}h"
                        
                        # Update channel with rate limit handling (Discord allows ~5 channel updates per 10 sec)
                        # Use exponential backoff on rate limit errors
                        max_retries = 3
                        retry_count = 0
                        retry_wait = 6  # Start with 6 seconds for retry backoff
                        
                        while retry_count < max_retries:
                            try:
                                await channel.edit(name=new_name, position=i)
                                break  # Success, exit retry loop
                            except discord.HTTPException as e:
                                if e.status == 429:  # Rate limited
                                    retry_count += 1
                                    if retry_count < max_retries:
                                        logging.warning(f"Rate limited on channel {channel_id}, retrying in {retry_wait}s... (attempt {retry_count})")
                                        await asyncio.sleep(retry_wait)
                                        retry_wait = min(retry_wait * 2, 60)  # Exponential backoff, max 60s
                                    else:
                                        logging.error(f"Rate limited {max_retries}x on channel {channel_id}, skipping")
                                else:
                                    # Other HTTP error
                                    logging.error(f"Failed to update leaderboard channel {channel_id}: {e}")
                                    break
                        
                        # Standard delay between channels (spacing out requests to avoid rate limits)
                        # Discord limit: ~5 PATCH requests per 10 seconds, so 2 seconds between requests
                        if i < len(rankings) - 1:  # Don't wait after last channel
                            await asyncio.sleep(2)
                    except Exception as e:
                        logging.error(f"Failed to update leaderboard channel {channel_id}: {e}")
                
            except Exception as e:
                logging.error(f"Leaderboard update error for guild {guild.id}: {e}")
            finally:
                # Always remove guild from updating set when done (success or error)
                self.leaderboard_updating.discard(guild_id)
                self.leaderboard_update_times.pop(guild_id, None)
            
            # Add delay between guild updates to avoid global rate limits
            # Only if there are more guilds to process
            if guild_idx < len(guild_list) - 1:
                await asyncio.sleep(5)
        
        gc.collect()
    
    @tasks.loop(minutes=5)
    async def voice_checkpoint(self):
        """Periodically checkpoint in-progress voice stats to prevent data loss on crash."""
        await self.bot.wait_until_ready()
        try:
            for guild in self.bot.guilds:
                self.checkpoint_voice_stats(guild.id)
        except Exception as e:
            logging.error(f"Periodic voice checkpoint error: {e}")

    @tasks.loop(minutes=5)
    async def monthly_reset_check(self):
        """Check if we need to reset voice stats at the start of a new month for all guilds."""
        await self.bot.wait_until_ready()
        
        now = datetime.now(self.config.VIETNAM_TZ)
        current_month = now.month
        
        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                guild_config = self.config.get_guild_config(guild_id)
                
                state = self.load_state(guild_id)
                last_reset_month = state.get("last_reset_month")
                
                # If we have no recorded last reset month, initialize it and skip reset
                if last_reset_month is None:
                    state["last_reset_month"] = current_month
                    self.save_state(guild_id, state)
                    continue
                
                # If already recorded for this month, nothing to do
                if last_reset_month == current_month:
                    continue
                
                # It's a new month -> perform reset
                logging.info(f"Monthly reset triggered for guild {guild_id}, month {current_month} (last: {last_reset_month})")
                
                # 1. Checkpoint current stats first
                self.checkpoint_voice_stats(guild_id)
                
                # 2. Validate and clean voice stats (remove non-competitors to prevent contamination)
                if self.validate_and_clean_voice_stats(guild_id):
                    logging.info(f"Cleaned contaminated voice stats for guild {guild_id}")
                
                # 3. Load final stats before reset
                stats = self.load_voice_stats(guild_id)
                
                # 4. Find Top 3 and Immortal/Legendary users
                rankings = []
                for user_id, total_seconds in stats.items():
                    total_hours = total_seconds / 3600
                    rank_name, role_id, perks, _ = self.get_user_rank(total_hours)
                    rankings.append((int(user_id), total_hours, rank_name))
                
                rankings.sort(key=lambda x: x[1], reverse=True)
                
                # 5. Prepare Hall of Fame message
                general_channel_id = guild_config.get_general_channel_id()
                if general_channel_id:
                    channel = self.bot.get_channel(general_channel_id)
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
                                # Use guild member for guild-specific display name
                                guild_member = guild.get_member(int(user_id))
                                name = guild_member.display_name if guild_member else f"<@{user_id}>"
                            except (discord.NotFound, discord.HTTPException):
                                logging.debug(f"User {user_id} not found for hall of fame")
                                name = f"<@{user_id}>"
                            except Exception as e:
                                logging.error(f"Error fetching user {user_id}: {e}")
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
                                    guild_member = guild.get_member(uid)
                                    display = guild_member.display_name if guild_member else f'<@{uid}>'
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
                            logging.error(f"Failed to send Hall of Fame for guild {guild_id}: {e}")
                
                # 5. Backup stats to archive file (archive to PREVIOUS month, not current)
                storage = self._get_storage()
                archive_year = now.year
                archive_month = now.month - 1 if now.month > 1 else 12
                if now.month == 1:
                    archive_year -= 1  # If January, archive goes to December of previous year
                
                if storage is not None:
                    try:
                        storage.archive_voice_stats(guild_id, archive_year, archive_month, stats)
                        logging.info(f"Archived stats for guild {guild_id} to SQLite ({archive_year}-{archive_month:02d})")
                    except Exception as e:
                        logging.error(f"Failed to archive stats for guild {guild_id}: {e}")
                else:
                    archive_filename = guild_config.get_file_path(f"archive_{archive_year}_{str(archive_month).zfill(2)}.json")
                    try:
                        with open(archive_filename, "w", encoding="utf-8") as f:
                            json.dump(stats, f, indent=2, ensure_ascii=False)
                        logging.info(f"Archived stats for guild {guild_id} to {archive_filename}")
                    except Exception as e:
                        logging.error(f"Failed to archive stats for guild {guild_id}: {e}")
                
                # 6. Reset all stats to 0
                reset_stats = {user_id: 0 for user_id in stats.keys()}
                self.save_voice_stats(guild_id, reset_stats)
                logging.info(f"Voice stats reset to 0 for all users in guild {guild_id}")
                
                # 7. Sync roles to match new stats (everyone back to Iron)
                try:
                    await self.apply_rank_roles_to_guild(guild)
                    logging.info(f"Monthly reset: roles synced for guild {guild_id}")
                except Exception as e:
                    logging.error(f"Failed to sync roles after monthly reset for guild {guild_id}: {e}")
                
                # 8. Update state
                state["last_reset_month"] = current_month
                self.save_state(guild_id, state)
                
                # 8.5. Reset economy purchases for this guild
                storage = self._get_storage()
                if storage:
                    storage.clear_purchases(guild_id)
                    logging.info(f"Economy purchases cleared for guild {guild_id}")
                
                # 9. SYNC: Update leaderboard immediately after reset (don't wait up to 55 min)
                logging.info(f"Syncing leaderboard immediately after reset for guild {guild_id}")
                try:
                    await self.update_leaderboard()
                except Exception as e:
                    logging.error(f"Failed to sync leaderboard after reset for guild {guild_id}: {e}")
                
            except Exception as e:
                logging.error(f"Monthly reset error for guild {guild.id}: {e}")
        
        gc.collect()
    
    # --- Event Handlers ---
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Track competitor voice time and handle entrance sounds for Diamond+ users."""
        # Only track competitors (users who signed up for the competition)
        guild_id = member.guild.id
        user_id = str(member.id)
        competitors = self.load_competitors(guild_id)
        if user_id not in competitors:
            return
        now = time.time()
        
        # Joined voice channel
        if before.channel is None and after.channel is not None:
            self.voice_join_times.setdefault(guild_id, {})[user_id] = now
            
            # Check rank for entrance sound (Diamond+)
            stats = self.load_voice_stats(guild_id)
            total_seconds = stats.get(user_id, 0)
            total_hours = total_seconds / 3600
            rank_name, role_id, perks, _ = self.get_user_rank(total_hours)
            logging.info(f"Voice join detected: {member.display_name} ({member.id}) rank={rank_name} hours={total_hours:.2f}")
            
            # Diamond+ ranks can have entrance sounds
            if rank_name in ["Diamond", "Elite", "Immortal", "Legendary"]:
                entry_settings = self.load_entry_settings(guild_id)
                user_settings = entry_settings.get(user_id, {"enabled": True, "type": "default"})
                logging.info(f"Entry settings for {member.display_name} ({member.id}): {user_settings}")
                
                # Check if entrance is enabled
                if user_settings.get("enabled", True):
                    # If audio is already playing, drop the entrance sound
                    if self.audio_lock.locked():
                        logging.info(f"Dropped entrance sound for {member.display_name} - audio lock busy")
                        return
                    logging.info(f"Scheduling entrance sound for {member.display_name} ({member.id})")
                    # Play entrance sound
                    asyncio.create_task(self.play_entrance_sound(member, after.channel, rank_name, user_settings))
        
        # Left voice channel
        elif before.channel is not None and after.channel is None:
            guild_times = self.voice_join_times.get(guild_id, {})
            if user_id in guild_times:
                start_time = guild_times.pop(user_id)
                duration = now - start_time
                
                # Immediately save to JSON (persistence!)
                stats = self.load_voice_stats(guild_id)
                if user_id not in stats:
                    stats[user_id] = 0
                
                stats[user_id] += duration
                
                self.save_voice_stats(guild_id, stats)
                
                # Economy: earn coins for this session
                total_hours = stats[user_id] / 3600
                _, _, _, mult = self.get_user_rank(total_hours)
                coins_earned = (duration / 600) * mult
                storage = self._get_storage()
                if storage:
                    storage.add_coins(guild_id, int(user_id), coins_earned)
                
                gc.collect()
    
    async def play_entrance_sound(self, member, voice_channel, rank_name, user_settings):
        """Play entrance sound for a user joining voice channel."""
        try:
            async with self.audio_lock:
                user_id = str(member.id)
                entry_type = user_settings.get("type", "default")
                
                # For Immortal/Legendary with custom setup, play custom sound
                if rank_name in ["Immortal", "Legendary"] and entry_type in ["tts", "file"]:
                    # Look for custom file
                    custom_files = [f"data/sfx/custom_{user_id}.mp3", f"data/sfx/custom_{user_id}.ogg"]
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
                            # Find existing voice client for this guild
                            for vc in self.bot.voice_clients:
                                if vc.guild.id == member.guild.id and vc.channel.id == voice_channel.id:
                                    voice_client = vc
                                    break
                            
                            if not voice_client:
                                voice_client = await voice_channel.connect()
                            
                            voice_client.play(discord.FFmpegPCMAudio(audio_file, executable=self.ffmpeg_exec))
                            
                            # Wait for playback to finish
                            while voice_client.is_playing():
                                await asyncio.sleep(0.1)
                            
                            await voice_client.disconnect()
                            return
                        except Exception as e:
                            logging.error(f"Failed to play custom entrance for {member.display_name}: {e}")
                
                # Default: Generate TTS "Xin chào {name}" for Diamond/Elite or fallback
                if rank_name in ["Diamond", "Elite", "Immortal", "Legendary"]:
                    temp_file = f"data/sfx/tts_entrance_{member.id}.mp3"
                    try:
                        message = f"Xin chào {member.display_name}"
                        logging.info(f"Generating TTS entrance for {member.display_name} ({member.id}): '{message}'")
                        tts = gTTS(text=message, lang='vi', slow=False)
                        await asyncio.to_thread(tts.save, temp_file)
                        
                        # Play TTS
                        voice_client = None
                        for vc in self.bot.voice_clients:
                            if vc.guild.id == member.guild.id and vc.channel.id == voice_channel.id:
                                voice_client = vc
                                break
                        
                        if not voice_client:
                            voice_client = await voice_channel.connect()
                        
                        voice_client.play(discord.FFmpegPCMAudio(temp_file, executable=self.ffmpeg_exec))
                        
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
    
    async def process_say_queue(self):
        """Background task to process /say commands from the queue."""
        while True:
            try:
                # Wait for next item in queue
                interaction, message_text = await self.say_queue.get()
                
                # Get user's voice channel
                if not interaction.user.voice or not interaction.user.voice.channel:
                    try:
                        await interaction.followup.send("❌ Bạn phải ở trong voice channel!", ephemeral=True)
                    except:
                        pass
                    continue
                
                voice_channel = interaction.user.voice.channel
                
                # Generate TTS file
                temp_file = f"data/sfx/tts_{interaction.id}.mp3"
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
                async with self.audio_lock:
                    try:
                        # Connect to voice
                        voice_client = None
                        for vc in self.bot.voice_clients:
                            if vc.guild.id == interaction.guild.id:
                                voice_client = vc
                                break
                        
                        if not voice_client or not voice_client.is_connected():
                            voice_client = await voice_channel.connect()
                        elif voice_client.channel.id != voice_channel.id:
                            await voice_client.move_to(voice_channel)
                        
                        # Play audio
                        voice_client.play(discord.FFmpegPCMAudio(temp_file, executable=self.ffmpeg_exec))
                        
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
    
    # --- Slash Commands ---
    
    @app_commands.command(name="sync_roles", description="(Admin) Sync rank roles for the guild now")
    @admin_only()
    async def sync_roles_cmd(self, interaction: discord.Interaction):
        """Manually sync rank roles."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if not guild:
            await interaction.followup.send("❌ Guild context required.", ephemeral=True)
            return
        try:
            await self.apply_rank_roles_to_guild(guild)
            await interaction.followup.send("✅ Role sync completed.", ephemeral=True)
        except Exception as e:
            logging.error(f"Manual role sync failed: {e}")
            await interaction.followup.send(f"❌ Role sync failed: {e}", ephemeral=True)
    
    @app_commands.command(name="refresh_leaderboard", description="(Admin) Force refresh voice leaderboard now")
    @admin_only()
    async def refresh_leaderboard_cmd(self, interaction: discord.Interaction):
        """Manually refresh leaderboard."""
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = interaction.guild.id
            # checkpoint and run update immediately
            self.checkpoint_voice_stats(guild_id)
            await self.update_leaderboard()
            await interaction.followup.send("✅ Leaderboard refreshed.", ephemeral=True)
        except Exception as e:
            logging.error(f"Manual leaderboard refresh failed: {e}")
            await interaction.followup.send(f"❌ Refresh failed: {e}", ephemeral=True)
    
    @app_commands.command(name="admin_force_reset", description="(Admin Only) Manually trigger monthly reset NOW")
    @admin_only()
    async def admin_force_reset_cmd(self, interaction: discord.Interaction):
        """Force monthly reset immediately (for testing/emergency)."""
        await interaction.response.defer(ephemeral=True)
        
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Admin only!", ephemeral=True)
            return
        
        try:
            guild = interaction.guild
            guild_id = guild.id
            guild_config = self.config.get_guild_config(guild_id)
            
            logging.info(f"⚠️  MANUAL FORCE RESET triggered by {interaction.user.display_name} for guild {guild_id}")
            
            # 1. Checkpoint current stats first
            self.checkpoint_voice_stats(guild_id)
            
            # 2. Load PREVIOUS MONTH's archived stats for hall of fame (not current fresh stats)
            stats = self.load_previous_month_archived_stats(guild_id)
            if not stats:
                logging.warning(f"No archived stats found for manual reset hall of fame, falling back to current stats")
                stats = self.load_voice_stats(guild_id)
            
            # 3. Find Top 3 and Immortal/Legendary users
            rankings = []
            for user_id, total_seconds in stats.items():
                total_hours = total_seconds / 3600
                rank_name, role_id, perks, _ = self.get_user_rank(total_hours)
                rankings.append((int(user_id), total_hours, rank_name))
            
            rankings.sort(key=lambda x: x[1], reverse=True)
            
            # 4. Prepare Hall of Fame message
            general_channel_id = guild_config.get_general_channel_id()
            if general_channel_id:
                channel = self.bot.get_channel(general_channel_id)
                if channel and rankings:
                    now = datetime.now(self.config.VIETNAM_TZ)
                    embed = discord.Embed(
                        title="🏆 HỘI ĐƯỜNG DANH VỌNG - THÁNG QUA 🏆",
                        description=f"Chúc mừng những chiến binh đã cống hiến thời gian cho server!",
                        color=discord.Color.gold()
                    )
                    
                    medals = ["🥇", "🥈", "🥉"]
                    top_3 = rankings[:3]
                    
                    for i, (user_id, hours, rank_name) in enumerate(top_3):
                        try:
                            # Use guild member for guild-specific display name
                            guild_member = guild.get_member(int(user_id))
                            name = guild_member.display_name if guild_member else f"<@{user_id}>"
                        except (discord.NotFound, discord.HTTPException):
                            logging.debug(f"User {user_id} not found for hall of fame")
                            name = f"<@{user_id}>"
                        except Exception as e:
                            logging.error(f"Error fetching user {user_id}: {e}")
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
                                guild_member = guild.get_member(uid)
                                display = guild_member.display_name if guild_member else f'<@{uid}>'
                            except Exception:
                                display = f'<@{uid}>'
                            elite_lines.append(f"⭐ {display}: **{rank}**")
                        elite_text = "\n".join(elite_lines)
                        embed.add_field(
                            name="💎 Immortal & Legendary Warriors",
                            value=elite_text[:1024],
                            inline=False
                        )
                    
                    embed.set_footer(text=f"⚠️ MANUAL RESET by {interaction.user.display_name} at {now.strftime('%d/%m/%Y %H:%M')} (Giờ Việt Nam)")
                    
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logging.error(f"Failed to send Hall of Fame for guild {guild_id}: {e}")
            
            # 5. Backup stats to archive file (archive to PREVIOUS month)
            storage = self._get_storage()
            now = datetime.now(self.config.VIETNAM_TZ)
            archive_year = now.year
            archive_month = now.month - 1 if now.month > 1 else 12
            if now.month == 1:
                archive_year -= 1  # If January, archive goes to December of previous year
            
            if storage is not None:
                try:
                    storage.archive_voice_stats(guild_id, archive_year, archive_month, stats)
                    logging.info(f"Archived stats for guild {guild_id} to SQLite ({archive_year}-{archive_month:02d})")
                except Exception as e:
                    logging.error(f"Failed to archive stats for guild {guild_id}: {e}")
            
            # 6. Reset all stats to 0
            reset_stats = {user_id: 0 for user_id in stats.keys()}
            self.save_voice_stats(guild_id, reset_stats)
            logging.info(f"Voice stats reset to 0 for all users in guild {guild_id}")
            
            # 7. Sync roles to match new stats (everyone back to Iron)
            try:
                await self.apply_rank_roles_to_guild(guild)
                logging.info(f"Manual reset: roles synced for guild {guild_id}")
            except Exception as e:
                logging.error(f"Failed to sync roles after manual reset for guild {guild_id}: {e}")
            
            # 8. Update state - increment month (or keep current if same month)
            state = self.load_state(guild_id)
            now = datetime.now(self.config.VIETNAM_TZ)
            current_month = now.month
            state["last_reset_month"] = current_month
            self.save_state(guild_id, state)
            
            # 8.5. Reset economy purchases for this guild
            storage = self._get_storage()
            if storage:
                storage.clear_purchases(guild_id)
                logging.info(f"Economy purchases cleared for guild {guild_id}")
            
            # 9. Update leaderboard immediately
            try:
                await self.update_leaderboard()
                logging.info(f"Leaderboard synced after manual reset for guild {guild_id}")
            except Exception as e:
                logging.error(f"Failed to sync leaderboard after manual reset: {e}")
            
            await interaction.followup.send(
                f"✅ **MANUAL RESET COMPLETED**\n"
                f"• Voice stats reset to 0\n"
                f"• Roles synced (all back to Iron)\n"
                f"• Leaderboard updated\n"
                f"• Hall of Fame posted",
                ephemeral=True
            )
            
            gc.collect()
        
        except Exception as e:
            logging.error(f"Manual force reset failed: {e}")
            await interaction.followup.send(f"❌ Reset failed: {e}", ephemeral=True)
    
    @app_commands.command(name="rank", description="Join or manage voice time competition")
    @app_commands.describe(
        action="Action: add, remove, list, or set",
        user="User to add/remove/set from competition (leave empty for add/list)",
        seconds="Seconds to set (required for 'set' action)"
    )
    async def rank_cmd(self, interaction: discord.Interaction, action: str, user: discord.Member = None, seconds: int = None, coins: int = None):
        """Manage voice time competition list."""
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            logging.warning(f"Interaction defer failed for /rank: {e}")
        
        guild_id = interaction.guild.id
        guild_config = self.config.get_guild_config(guild_id)
        
        if action.lower() == "add":
            target_user = user if user else interaction.user
            user_id = str(target_user.id)
            
            # Admin check only if adding someone else
            if user and not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ You can only add yourself. Use `/rank add` without specifying a user.", ephemeral=True)
                return
            
            competitors = self.load_competitors(guild_id)
            
            if user_id in competitors:
                await interaction.followup.send(f"⚠️ {target_user.display_name} is already in the competition.", ephemeral=True)
                return
            
            # Initialize stats for new competitor
            stats = self.load_voice_stats(guild_id)
            if user_id not in stats:
                stats[user_id] = 0
                self.save_voice_stats(guild_id, stats)
            
            # Create voice channel
            try:
                rank_category_id = guild_config.get_rank_category_id()
                category = self.bot.get_channel(rank_category_id)
                if not category:
                    await interaction.followup.send("❌ Rank category not found. Please check guild config.", ephemeral=True)
                    return
                
                total_hours = stats.get(user_id, 0) / 3600
                
                new_channel = await category.create_voice_channel(
                    name=f"🏅 {target_user.display_name}: {int(total_hours)}h",
                    reason=f"Rank channel for {target_user.display_name}"
                )
                
                competitors[user_id] = str(new_channel.id)
                self.save_competitors(guild_id, competitors)
                
                await interaction.followup.send(f"✅ {target_user.display_name} joined the competition! Channel created: {new_channel.mention}", ephemeral=True)
                gc.collect()
            except Exception as e:
                await interaction.followup.send(f"❌ Failed to create channel: {e}", ephemeral=True)
                logging.error(f"Failed to create rank channel: {e}")
        
        elif action.lower() == "remove":
            if user and not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Only admins can remove other users.", ephemeral=True)
                return
            
            target_user = user if user else interaction.user
            user_id = str(target_user.id)
            
            competitors = self.load_competitors(guild_id)
            
            if user_id not in competitors:
                await interaction.followup.send(f"⚠️ {target_user.display_name} is not in the competition.", ephemeral=True)
                return
            
            # Delete the channel
            channel_id = competitors[user_id]
            if channel_id:
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await channel.delete(reason=f"Removed {target_user.display_name} from competition")
                except Exception as e:
                    logging.error(f"Failed to delete channel {channel_id}: {e}")
            
            del competitors[user_id]
            self.save_competitors(guild_id, competitors)
            
            await interaction.followup.send(f"✅ {target_user.display_name} removed from voice time competition.", ephemeral=True)
            gc.collect()
        
        elif action.lower() == "list":
            # Checkpoint: Update stats for people currently in voice before displaying
            self.checkpoint_voice_stats(guild_id)
            
            competitors = self.load_competitors(guild_id)
            if not competitors:
                await interaction.followup.send("📊 No competitors registered yet.", ephemeral=True)
                return
            
            # Get all-time totals (current + archived months)
            stats = self.load_all_time_stats(guild_id)
            
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
                    # Use guild member for guild-specific display name
                    guild_member = guild.get_member(uid)
                    name = guild_member.display_name if guild_member else f"<@{uid}>"
                except:
                    name = f"<@{uid}>"
                
                medal = medals[i] if i < len(medals) else f"#{i+1}"
                msg += f"{medal} **{name}**: {int(hours)}h {int((hours % 1) * 60)}m\n"
            
            await interaction.followup.send(msg, ephemeral=True)
            gc.collect()
        
        elif action.lower() == "set":
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Only admins can set voice hours.", ephemeral=True)
                return
            
            if not user:
                await interaction.followup.send("❌ You must specify a user to set hours for.", ephemeral=True)
                return
            
            if seconds is None or seconds < 0:
                await interaction.followup.send("❌ Please provide a valid number of seconds (0 or greater).", ephemeral=True)
                return
            
            user_id = str(user.id)
            stats = self.load_voice_stats(guild_id)
            old_seconds = stats.get(user_id, 0)
            stats[user_id] = seconds
            self.save_voice_stats(guild_id, stats)
            
            old_hours = int(old_seconds / 3600)
            new_hours = int(seconds / 3600)
            new_mins = int((seconds % 3600) / 60)
            
            await interaction.followup.send(
                f"✅ {user.display_name}'s voice time updated:\n"
                f"**Before:** {old_hours}h\n"
                f"**After:** {new_hours}h {new_mins}m ({seconds} seconds)",
                ephemeral=True
            )
            gc.collect()
        
        elif action.lower() == "coin":
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Only admins can give coins.", ephemeral=True)
                return
            if not user or coins is None or coins <= 0:
                await interaction.followup.send("❌ Please specify a user and a positive coin amount.", ephemeral=True)
                return
            storage = self._get_storage()
            if storage:
                new_balance = storage.add_coins(guild_id, user.id, float(coins))
                await interaction.followup.send(f"✅ Added {coins}🪙 to {user.display_name}. New balance: {new_balance}🪙", ephemeral=True)
            else:
                await interaction.followup.send("❌ Economy storage not available.", ephemeral=True)
            gc.collect()
        
        else:
            await interaction.followup.send("❌ Invalid action! Use 'add', 'remove', 'list', 'set', or 'coin'.", ephemeral=True)
    
    @app_commands.command(name="say", description="Make Beanie speak in your voice channel (Gold+ rank)")
    @app_commands.describe(message="Text message to speak (max 50 characters)")
    async def say_cmd(self, interaction: discord.Interaction, message: str):
        """Text-to-speech command for Gold+ ranked users."""
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            logging.warning(f"Interaction defer failed for /say: {e}")
        
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        # Check rank
        stats = self.load_voice_stats(guild_id)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks, _ = self.get_user_rank(total_hours)
        
        # Must be Gold+ rank
        if rank_name not in ["Gold", "Platinum", "Diamond", "Elite", "Immortal", "Legendary"]:
            await interaction.followup.send(f"❌ Chỉ Gold rank trở lên mới dùng được /say! (Rank hiện tại: {rank_name})", ephemeral=True)
            return
        
        # Check cooldown
        now = time.time()
        last_use = self.say_cooldowns.get(user_id, 0)
        if now - last_use < 5:
            remaining = 5 - (now - last_use)
            await interaction.followup.send(f"⏳ Cooldown: chờ {remaining:.1f}s nữa!", ephemeral=True)
            return
        
        # Validate message length (base 50 + purchased tokens)
        max_chars = 50
        storage = self._get_storage()
        if storage:
            month = datetime.now().strftime("%Y-%m")
            purchased = storage.get_purchase(guild_id, int(user_id), month, "say_tokens")
            max_chars += int(purchased)
        if len(message) > max_chars:
            await interaction.followup.send(f"❌ Message quá dài! Tối đa {max_chars} characters.", ephemeral=True)
            return
        
        # Check if user is in voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("❌ Bạn phải ở trong voice channel!", ephemeral=True)
            return
        
        # Try to add to queue
        try:
            self.say_queue.put_nowait((interaction, message))
            self.say_cooldowns[user_id] = now
            await interaction.followup.send(f"✅ Đã thêm vào hàng đợi: '{message}'", ephemeral=True)
        except asyncio.QueueFull:
            await interaction.followup.send("❌ Bot đang quá tải audio, chờ xíu!", ephemeral=True)
    
    def cog_unload(self):
        """Called when cog is unloaded."""
        self.update_leaderboard.cancel()
        self.monthly_reset_check.cancel()
        self.periodic_role_sync.cancel()
        self.voice_checkpoint.cancel()


# Entry command group setup
class EntryCommandsGroup(commands.GroupCog, name="entry", description="Manage entrance sound settings"):
    def __init__(self, bot, voice_feature):
        self.bot = bot
        self.voice_feature = voice_feature
        super().__init__()
    
    @app_commands.command(name="on", description="Enable entrance sound (Diamond+ rank)")
    async def entry_on(self, interaction: discord.Interaction):
        """Enable entrance sound for Diamond+ users."""
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        # Check rank
        stats = self.voice_feature.load_voice_stats(guild_id)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks, _ = self.voice_feature.get_user_rank(total_hours)
        
        if rank_name not in ["Diamond", "Elite", "Immortal", "Legendary"]:
            await interaction.response.send_message(f"❌ Chỉ Diamond rank trở lên mới có entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
            return
        
        entry_settings = self.voice_feature.load_entry_settings(guild_id)
        if user_id not in entry_settings:
            entry_settings[user_id] = {"enabled": True, "type": "default"}
        else:
            entry_settings[user_id]["enabled"] = True
        self.voice_feature.save_entry_settings(guild_id, entry_settings)
        
        await interaction.response.send_message("✅ Entrance sound đã BẬT!", ephemeral=True)
    
    @app_commands.command(name="off", description="Disable entrance sound (Diamond+ rank)")
    async def entry_off(self, interaction: discord.Interaction):
        """Disable entrance sound for Diamond+ users."""
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        # Check rank
        stats = self.voice_feature.load_voice_stats(guild_id)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks, _ = self.voice_feature.get_user_rank(total_hours)
        
        if rank_name not in ["Diamond", "Elite", "Immortal", "Legendary"]:
            await interaction.response.send_message(f"❌ Chỉ Diamond rank trở lên mới có entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
            return
        
        entry_settings = self.voice_feature.load_entry_settings(guild_id)
        if user_id not in entry_settings:
            entry_settings[user_id] = {"enabled": False, "type": "default"}
        else:
            entry_settings[user_id]["enabled"] = False
        self.voice_feature.save_entry_settings(guild_id, entry_settings)
        
        await interaction.response.send_message("✅ Entrance sound đã TẮT!", ephemeral=True)
    
    @app_commands.command(name="add", description="Add custom entrance sound (Immortal+ rank)")
    async def entry_add(self, interaction: discord.Interaction):
        """Add custom entrance sound for Immortal+ users."""
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        # Check rank
        stats = self.voice_feature.load_voice_stats(guild_id)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks, _ = self.voice_feature.get_user_rank(total_hours)
        
        if rank_name not in ["Immortal", "Legendary"]:
            await interaction.response.send_message(f"❌ Chỉ Immortal rank trở lên mới tùy chỉnh entrance sound! (Rank hiện tại: {rank_name})", ephemeral=True)
            return
        
        # Show button view
        view = EntryCustomizeView(user_id, guild_id)
        await interaction.response.send_message("🎵 Chọn cách tùy chỉnh entrance sound:", view=view, ephemeral=True)
    
    @app_commands.command(name="upload", description="Upload custom audio file (Immortal+ rank)")
    @app_commands.describe(file="Audio file (.mp3 or .ogg, max 200KB)")
    async def entry_upload(self, interaction: discord.Interaction, file: discord.Attachment):
        """Upload custom audio file for entrance sound."""
        await interaction.response.defer(ephemeral=True)
        
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        
        # Check rank
        stats = self.voice_feature.load_voice_stats(guild_id)
        total_seconds = stats.get(user_id, 0)
        total_hours = total_seconds / 3600
        rank_name, role_id, perks, _ = self.voice_feature.get_user_rank(total_hours)
        
        if rank_name not in ["Immortal", "Legendary"]:
            await interaction.followup.send(f"❌ Chỉ Immortal rank trở lên mới upload custom audio! (Rank hiện tại: {rank_name})", ephemeral=True)
            return
        
        # Validate file size (base 200KB + purchased storage)
        max_bytes = 200 * 1024
        storage = self.voice_feature._get_storage()
        if storage:
            month = datetime.now().strftime("%Y-%m")
            purchased_kb = storage.get_purchase(guild_id, int(user_id), month, "entry_storage")
            max_bytes += int(purchased_kb) * 1024
        if file.size > max_bytes:
            await interaction.followup.send(f"❌ File quá lớn! Tối đa {max_bytes // 1024}KB (file của bạn: {file.size // 1024}KB)", ephemeral=True)
            return
        
        # Validate file extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".mp3", ".ogg"]:
            await interaction.followup.send("❌ Chỉ hỗ trợ .mp3 hoặc .ogg!", ephemeral=True)
            return
        
        # Delete old custom files
        for old_ext in [".mp3", ".ogg"]:
            old_file = f"data/sfx/custom_{user_id}{old_ext}"
            try:
                if os.path.exists(old_file):
                    os.remove(old_file)
            except Exception as e:
                logging.warning(f"Failed to delete old custom file {old_file}: {e}")
        
        # Save new file
        custom_file = f"data/sfx/custom_{user_id}{ext}"
        try:
            await file.save(custom_file)
            
            # Update settings
            entry_settings = self.voice_feature.load_entry_settings(guild_id)
            entry_settings[user_id] = {"enabled": True, "type": "file"}
            self.voice_feature.save_entry_settings(guild_id, entry_settings)
            
            await interaction.followup.send(f"✅ Đã upload custom entrance sound! ({file.filename})", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Upload failed: {e}", ephemeral=True)


# UI Views
class EntryCustomizeView(discord.ui.View):
    __slots__ = ('user_id', 'guild_id')
    
    def __init__(self, user_id, guild_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.guild_id = guild_id
    
    @discord.ui.button(label="Nhập TTS", style=discord.ButtonStyle.primary, emoji="💬")
    async def tts_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EntryTTSModal(self.user_id, self.guild_id)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Upload File", style=discord.ButtonStyle.secondary, emoji="📁")
    async def upload_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📁 Sử dụng lệnh `/entry upload` kèm file .mp3 (dung lượng tối đa theo cấp độ)",
            ephemeral=True
        )


class EntryTTSModal(discord.ui.Modal, title="Custom TTS Entrance"):
    __slots__ = ('user_id', 'guild_id')
    
    tts_text = discord.ui.TextInput(
        label="Nhập text cho TTS",
        placeholder="Xin chào...",
        max_length=50,
        required=True
    )
    
    def __init__(self, user_id, guild_id):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        text = self.tts_text.value.strip()
        if not text:
            await interaction.followup.send("❌ Text không được để trống!", ephemeral=True)
            return
        
        # Delete old custom files
        for old_ext in [".mp3", ".ogg"]:
            old_file = f"data/sfx/custom_{self.user_id}{old_ext}"
            try:
                if os.path.exists(old_file):
                    os.remove(old_file)
            except Exception as e:
                logging.warning(f"Failed to delete old custom file {old_file}: {e}")
        
        # Generate TTS file
        custom_file = f"data/sfx/custom_{self.user_id}.mp3"
        try:
            tts = gTTS(text=text, lang='vi', slow=False)
            await asyncio.to_thread(tts.save, custom_file)
            
            # Get voice_feature from bot
            voice_feature = interaction.client.get_cog("VoiceTrackingFeature")
            if voice_feature:
                entry_settings = voice_feature.load_entry_settings(self.guild_id)
                entry_settings[self.user_id] = {"enabled": True, "type": "tts", "text": text}
                voice_feature.save_entry_settings(self.guild_id, entry_settings)
            
            await interaction.followup.send(f"✅ Đã tạo custom TTS entrance: '{text}'", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ TTS generation failed: {e}", ephemeral=True)


async def setup(bot):
    """Setup function for the Voice Tracking feature."""
    # This will be called by bot.load_extension()
    # The main.py should pass required dependencies
    pass
