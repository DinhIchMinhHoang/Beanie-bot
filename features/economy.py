"""
Economy Feature Module for Beanie Bot
Handles coins, shop, gifting, and leaderboard for voice chat competition
"""

import logging
import gc
import time
from datetime import datetime
from discord.ext import commands
from discord import app_commands
import discord

SHOP_ITEMS = {
    "hours_1":    {"name": "1 Hour",       "type": "hours",         "value": 1,    "cost": 60,   "category": "hours", "emoji": "\U0001f3ab"},
    "hours_2":    {"name": "2 Hours",      "type": "hours",         "value": 2,    "cost": 110,  "category": "hours", "emoji": "\U0001f3ab"},
    "hours_5":    {"name": "5 Hours",      "type": "hours",         "value": 5,    "cost": 260,  "category": "hours", "emoji": "\U0001f3ab"},
    "hours_10":   {"name": "10 Hours",     "type": "hours",         "value": 10,   "cost": 500,  "category": "hours", "emoji": "\U0001f3ab"},
    "hours_20":   {"name": "20 Hours",     "type": "hours",         "value": 20,   "cost": 950,  "category": "hours", "emoji": "\U0001f3ab"},
    "hours_50":   {"name": "50 Hours",     "type": "hours",         "value": 50,   "cost": 2400, "category": "hours", "emoji": "\U0001f3ab"},
    "hours_100":  {"name": "100 Hours",    "type": "hours",         "value": 100,  "cost": 5200, "category": "hours", "emoji": "\U0001f3ab"},
    "sound_100":  {"name": "+100KB Sound", "type": "entry_storage", "value": 100,  "cost": 350,  "category": "sound", "emoji": "\U0001f50a"},
    "sound_200":  {"name": "+200KB Sound", "type": "entry_storage", "value": 200,  "cost": 650,  "category": "sound", "emoji": "\U0001f50a"},
    "sound_500":  {"name": "+500KB Sound", "type": "entry_storage", "value": 500,  "cost": 1500, "category": "sound", "emoji": "\U0001f50a"},
    "say_50":     {"name": "+50 Chars",    "type": "say_tokens",    "value": 50,   "cost": 200,  "category": "say",   "emoji": "\U0001f4ac"},
    "say_100":    {"name": "+100 Chars",   "type": "say_tokens",    "value": 100,  "cost": 400,  "category": "say",   "emoji": "\U0001f4ac"},
    "say_200":    {"name": "+200 Chars",   "type": "say_tokens",    "value": 200,  "cost": 750,  "category": "say",   "emoji": "\U0001f4ac"},
    "say_500":    {"name": "+500 Chars",   "type": "say_tokens",    "value": 500,  "cost": 1600, "category": "say",   "emoji": "\U0001f4ac"},
}

ITEMS_BY_CATEGORY = {
    "hours": {k: v for k, v in SHOP_ITEMS.items() if v["category"] == "hours"},
    "sound": {k: v for k, v in SHOP_ITEMS.items() if v["category"] == "sound"},
    "say":   {k: v for k, v in SHOP_ITEMS.items() if v["category"] == "say"},
}

CATEGORY_META = {
    "hours": {"label": "Hours", "emoji": "\U0001f3ab", "description": "Buy voice hours to boost your rank"},
    "sound": {"label": "Entry Sound", "emoji": "\U0001f50a", "description": "Increase entrance sound storage"},
    "say":   {"label": "Say Tokens", "emoji": "\U0001f4ac", "description": "Extend your /say text limit"},
}


class ShopView(discord.ui.View):
    def __init__(self, cog, user_id, guild_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_category = None
        self._build_main()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("\u274c This shop is not for you!", ephemeral=True)
            return False
        return True

    def _build_main(self):
        self.clear_items()
        self.current_category = None
        select = CategorySelect(self)
        self.add_item(select)
        close = CloseButton(self)
        self.add_item(close)

    def _build_category(self, category):
        self.clear_items()
        self.current_category = category
        items = list(ITEMS_BY_CATEGORY.get(category, {}).items())
        for i, (key, info) in enumerate(items):
            row = i // 5
            cap_key = key
            cap_info = info
            btn = discord.ui.Button(
                label=f"{info['emoji']} {info['name']} - {info['cost']}\U0001fa99",
                style=discord.ButtonStyle.secondary,
                row=row,
                custom_id=f"buy_{key}",
            )
            async def item_cb(interaction, k=cap_key, i=cap_info):
                await self._on_item_click(interaction, k, i)
            btn.callback = item_cb
            self.add_item(btn)
        back = BackButton(self)
        self.add_item(back)
        close = CloseButton(self)
        self.add_item(close)

    def _build_confirmation(self, key, info):
        self.clear_items()
        confirm = discord.ui.Button(
            label=f"\u2705 Confirm: {info['name']} for {info['cost']}\U0001fa99",
            style=discord.ButtonStyle.success,
            row=0,
            custom_id=f"confirm_{key}",
        )
        async def confirm_cb(interaction):
            await self._execute_purchase(interaction, key, info)
        confirm.callback = confirm_cb
        self.add_item(confirm)

        cancel = discord.ui.Button(
            label="\U0001f6ab Cancel",
            style=discord.ButtonStyle.danger,
            row=1,
            custom_id="cancel_purchase",
        )
        async def cancel_cb(interaction):
            await self._on_back(interaction)
        cancel.callback = cancel_cb
        self.add_item(cancel)

    async def _on_item_click(self, interaction, key, info):
        balance = self.cog.get_balance(self.guild_id, self.user_id)
        if balance < info["cost"]:
            await interaction.response.edit_message(
                content=None,
                embed=discord.Embed(
                    title="\u274c Insufficient Coins",
                    description=f"You need **{info['cost']}\U0001fa99** but only have **{balance}\U0001fa99**.",
                    color=discord.Color.red()
                ),
                view=self,
            )
            return
        self._build_confirmation(key, info)
        embed = discord.Embed(
            title="\u2705 Confirm Purchase",
            description=f"**Item:** {info['emoji']} {info['name']}\n"
                        f"**Cost:** {info['cost']}\U0001fa99\n"
                        f"**Your balance:** {balance}\U0001fa99",
            color=discord.Color.gold()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def _execute_purchase(self, interaction, key, info):
        storage = self.cog._get_storage()
        if not storage:
            await interaction.response.edit_message(
                embed=discord.Embed(title="\u274c Error", description="Economy system unavailable.", color=discord.Color.red()),
                view=None,
            )
            return
        success = storage.spend_coins(self.guild_id, self.user_id, info["cost"])
        if not success:
            await interaction.response.edit_message(
                embed=discord.Embed(title="\u274c Purchase Failed", description="Insufficient coins.", color=discord.Color.red()),
                view=self,
            )
            return
        month = datetime.now().strftime("%Y-%m")
        storage.add_purchase(self.guild_id, self.user_id, month, info["type"], info["value"])
        new_balance = self.cog.get_balance(self.guild_id, self.user_id)
        embed = discord.Embed(
            title="\u2705 Purchase Successful!",
            description=f"**{info['emoji']} {info['name']}** added!\n"
                        f"**Remaining balance:** {new_balance}\U0001fa99\n\n"
                        f"*Purchases reset at month end.*",
            color=discord.Color.green()
        )
        self._build_main()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back(self, interaction):
        self.current_category = None
        embed = self.cog._build_shop_embed(self.guild_id, self.user_id)
        self._build_main()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        self.clear_items()


class CategorySelect(discord.ui.Select):
    def __init__(self, view):
        options = []
        for cat_id, meta in CATEGORY_META.items():
            options.append(discord.SelectOption(
                label=meta["label"],
                value=cat_id,
                emoji=meta["emoji"],
                description=meta["description"],
            ))
        super().__init__(
            placeholder="Select a category to browse...",
            options=options,
            row=0,
        )
        self.shop_view = view

    async def callback(self, interaction):
        category = self.values[0]
        self.shop_view._build_category(category)
        embed = self.shop_view.cog._build_category_embed(
            self.shop_view.guild_id, self.shop_view.user_id, category
        )
        await interaction.response.edit_message(embed=embed, view=self.shop_view)


class BackButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="\U0001f3e0 Back to Categories", style=discord.ButtonStyle.secondary, row=4)
        self.shop_view = view

    async def callback(self, interaction):
        await self.shop_view._on_back(interaction)


class CloseButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(
            label="\u274c Close",
            style=discord.ButtonStyle.danger,
            row=4,
            custom_id="shop_close",
        )
        self.shop_view = view

    async def callback(self, interaction):
        self.shop_view.clear_items()
        await interaction.response.edit_message(
            content="\U0001f6d2 Shop closed.",
            embed=None,
            view=None,
        )


class EconomyFeature(commands.Cog):
    def __init__(self, bot, config, voice_feature):
        self.bot = bot
        self.config = config
        self.voice_feature = voice_feature
        self.tree = bot.tree

    def _get_storage(self):
        storage_getter = getattr(self.config, "get_storage", None)
        if not callable(storage_getter):
            return None
        storage = storage_getter()
        return storage if hasattr(storage, "get_balance") else None

    def get_balance(self, guild_id: int, user_id: int) -> float:
        storage = self._get_storage()
        if storage:
            return storage.get_balance(guild_id, user_id)
        return 0.0

    def _build_shop_embed(self, guild_id, user_id):
        balance = self.get_balance(guild_id, user_id)
        embed = discord.Embed(
            title="\U0001fa99 Beanie Shop",
            description=f"**Your balance:** {balance}\U0001fa99\n\n"
                        "Select a category below to browse items.\n"
                        "All purchases reset at the end of each month.",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Coins carry over between months | Click an item to buy")
        return embed

    def _build_category_embed(self, guild_id, user_id, category):
        meta = CATEGORY_META.get(category, {})
        balance = self.get_balance(guild_id, user_id)
        embed = discord.Embed(
            title=f"{meta.get('emoji', '')} {meta.get('label', category)}",
            description=f"**Your balance:** {balance}\U0001fa99\n\n"
                        "Click any item to purchase.\n"
                        "*All purchases reset at month end.*",
            color=discord.Color.blue()
        )
        items = ITEMS_BY_CATEGORY.get(category, {})
        for key, info in items.items():
            embed.add_field(
                name=f"{info['emoji']} {info['name']}",
                value=f"Cost: **{info['cost']}\U0001fa99**",
                inline=True,
            )
        return embed

    @app_commands.command(name="eco", description="Check your economy balance and purchases")
    async def eco_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        balance = self.get_balance(guild_id, user_id)
        storage = self._get_storage()
        purchases = {}
        if storage:
            month = datetime.now().strftime("%Y-%m")
            purchases = storage.get_all_purchases(guild_id, user_id, month)

        purchased_hours = int(purchases.get("hours", 0))
        sound_kb = int(purchases.get("entry_storage", 0))
        say_chars = int(purchases.get("say_tokens", 0))

        # Current earning rate
        voice_feature = self.voice_feature
        stats = voice_feature.load_voice_stats(guild_id) if voice_feature else {}
        total_seconds = stats.get(str(user_id), 0) + purchased_hours * 3600
        total_hours = total_seconds / 3600
        _, _, _, mult = voice_feature.get_user_rank(total_hours) if voice_feature else (None, None, [], 1.0)
        earn_rate = 6 * mult  # 6 coins/hour base

        embed = discord.Embed(
            title="\U0001fa99 Your Economy",
            color=discord.Color.gold()
        )
        embed.add_field(name="Coins", value=f"{balance}\U0001fa99", inline=True)
        embed.add_field(name="Earning Rate", value=f"{earn_rate:.1f}\U0001fa99/h", inline=True)
        embed.add_field(name="Rank Multiplier", value=f"\u00d7{mult}", inline=True)
        embed.add_field(name="\U0001f3ab Purchased Hours (this month)", value=f"{purchased_hours}h", inline=True)
        embed.add_field(name="\U0001f50a Sound Storage (this month)", value=f"+{sound_kb}KB", inline=True)
        embed.add_field(name="\U0001f4ac Say Chars (this month)", value=f"+{say_chars}", inline=True)
        embed.set_footer(text="Purchases reset at month end. Coins carry over.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="shop", description="Open the Beanie Shop to spend your coins")
    async def shop_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        user_id = interaction.user.id

        embed = self._build_shop_embed(guild_id, user_id)
        view = ShopView(self, user_id, guild_id)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="gift", description="Gift coins to another user (10% tax)")
    @app_commands.describe(user="The user to gift", amount="Amount of coins to send")
    async def gift_cmd(self, interaction: discord.Interaction, user: discord.User, amount: int):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        sender_id = interaction.user.id

        if user.id == sender_id:
            await interaction.followup.send("\u274c You cannot gift coins to yourself!", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("\u274c Amount must be positive!", ephemeral=True)
            return
        if amount < 10:
            await interaction.followup.send("\u274c Minimum gift is 10\U0001fa99!", ephemeral=True)
            return

        storage = self._get_storage()
        if not storage:
            await interaction.followup.send("\u274c Economy system unavailable.", ephemeral=True)
            return

        tax = int(amount * 0.1)
        total_deduct = amount + tax

        balance = storage.get_balance(guild_id, sender_id)
        if balance < total_deduct:
            await interaction.followup.send(
                f"\u274c You need **{total_deduct}\U0001fa99** (including {tax}\U0001fa99 tax) but only have **{balance}\U0001fa99**.",
                ephemeral=True,
            )
            return

        success = storage.spend_coins(guild_id, sender_id, total_deduct)
        if not success:
            await interaction.followup.send("\u274c Transaction failed.", ephemeral=True)
            return

        storage.add_coins(guild_id, user.id, float(amount))

        sender_new = storage.get_balance(guild_id, sender_id)
        await interaction.followup.send(
            f"\u2705 Gifted **{amount}\U0001fa99** to {user.display_name}! (Tax: {tax}\U0001fa99)\n"
            f"Your new balance: {sender_new}\U0001fa99",
            ephemeral=True,
        )

    @app_commands.command(name="richest", description="View the coin leaderboard")
    async def richest_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        storage = self._get_storage()
        if not storage:
            await interaction.followup.send("\u274c Economy system unavailable.", ephemeral=True)
            return

        leaderboard = storage.get_coin_leaderboard(guild_id, 10)
        if not leaderboard:
            await interaction.followup.send("No one has earned any coins yet!", ephemeral=True)
            return

        embed = discord.Embed(
            title="\U0001fa99 Richest Competitors",
            color=discord.Color.gold()
        )

        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, (user_id, coins) in enumerate(leaderboard):
            medal = medals[i] if i < len(medals) else f"**#{i + 1}**"
            try:
                member = interaction.guild.get_member(user_id)
                name = member.display_name if member else f"<@{user_id}>"
            except Exception:
                name = f"<@{user_id}>"
            embed.add_field(
                name=f"{medal} {name}",
                value=f"{coins}\U0001fa99",
                inline=False,
            )

        embed.set_footer(text="Coins are earned by spending time in voice channels")
        await interaction.followup.send(embed=embed, ephemeral=True)
