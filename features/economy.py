"""
Economy Feature Module for Beanie Bot
Handles coins, shop, gifting, leaderboard, events, and notifications
"""

import asyncio
import logging
import gc
import time
import json
from datetime import datetime, date, timezone
from typing import Optional
from discord.ext import commands, tasks
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

# ── Lunar New Year Lookup Table (auto-calculated, no admin override) ────
_LUNAR_NEW_YEAR = {
    2024: (2, 10), 2025: (1, 29), 2026: (2, 17), 2027: (2, 6),
    2028: (1, 26), 2029: (2, 13), 2030: (2, 3),  2031: (1, 23),
    2032: (2, 11), 2033: (1, 31), 2034: (2, 19), 2035: (2, 8),
    2036: (1, 28), 2037: (2, 15), 2038: (2, 4),  2039: (1, 24),
    2040: (2, 12),
}

BUILTIN_EVENTS = [
    {
        "id": "monthly_match",
        "label": "Ngày Đặc Biệt Tháng",
        "discount": 0.4,
        "mult": 2.0,
        "check": lambda d: 1 <= d.month <= 12 and d.day == d.month,
    },
    {
        "id": "labor_day",
        "label": "Quốc Tế Lao Động 1/5",
        "discount": 0.2,
        "mult": 2.0,
        "check": lambda d: d.month == 5 and d.day == 1,
    },
    {
        "id": "independence_day",
        "label": "Quốc Khánh 2/9",
        "discount": 0.2,
        "mult": 2.0,
        "check": lambda d: d.month == 9 and d.day == 2,
    },
    {
        "id": "halloween",
        "label": "Halloween 31/10",
        "discount": 0.2,
        "mult": 2.0,
        "check": lambda d: d.month == 10 and d.day == 31,
    },
    {
        "id": "black_friday",
        "label": "Black Friday",
        "discount": 0.6,
        "mult": 2.0,
        "check": lambda d: d.month == 11 and d.weekday() == 4 and (d.day - 1) // 7 == 3,
    },
    {
        "id": "christmas",
        "label": "Giáng Sinh 25/12",
        "discount": 0.5,
        "mult": 2.0,
        "check": lambda d: d.month == 12 and d.day == 25,
    },
]

def _is_lunar_new_year(d: date) -> bool:
    entry = _LUNAR_NEW_YEAR.get(d.year)
    return entry is not None and entry[0] == d.month and entry[1] == d.day

# ── Event Helpers ────────────────────────────────────────────────────────

def get_matching_builtin_events(now: datetime | None = None) -> list[dict]:
    if now is None:
        now = datetime.now(timezone.UTC)
    d = now.date()
    results = []
    for ev in BUILTIN_EVENTS:
        if ev["check"](d):
            results.append({**ev})
    if _is_lunar_new_year(d):
        results.append({
            "id": "lunar_new_year",
            "label": "Tết Nguyên Đán",
            "discount": 0.4,
            "mult": 2.0,
            "check": lambda d: True,
        })
    return results

def get_active_events(storage, guild_id: int, now: datetime | None = None) -> list[dict]:
    if now is None:
        now = datetime.now(timezone.UTC)
    builtin = get_matching_builtin_events(now)
    custom = storage.get_active_custom_events(guild_id, now.isoformat()) if storage else []
    for ev in custom:
        ev["_custom"] = True
    return builtin + custom

def get_coin_multiplier(storage, guild_id: int) -> float:
    mult = 1.0
    for ev in get_active_events(storage, guild_id):
        mult *= ev.get("mult", 1.0)
    return mult

def get_shop_discount(storage, guild_id: int) -> float:
    best = 0.0
    for ev in get_active_events(storage, guild_id):
        if ev.get("event_type", "both") in ("shop_discount", "both"):
            best = max(best, ev.get("discount", 0))
    return min(best, 0.8)

def compute_item_discounts(storage, guild_id: int) -> dict[str, float]:
    best = get_shop_discount(storage, guild_id)
    if best <= 0:
        return {}
    return {key: best for key in SHOP_ITEMS}

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
        storage = self.cog._get_storage()
        self.discounts = compute_item_discounts(storage, self.guild_id) if storage else {}
        self.sale_active = bool(self.discounts)
        self._build_main()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("\u274c This shop is not for you!", ephemeral=True)
            return False
        return True

    def _sale_price(self, info):
        d = self.discounts.get(info["category"], 0)
        if d > 0:
            return round(info["cost"] * (1 - d))
        return info["cost"]

    def _item_label(self, info):
        sale_px = self._sale_price(info)
        if sale_px < info["cost"]:
            return f"{info['emoji']} {info['name']} - {sale_px}\U0001fa99 \U0001f525"
        return f"{info['emoji']} {info['name']} - {info['cost']}\U0001fa99"

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
            sale_px = self._sale_price(info)
            style = discord.ButtonStyle.success if sale_px < info["cost"] else discord.ButtonStyle.secondary
            btn = discord.ui.Button(
                label=self._item_label(info),
                style=style,
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
        sale_px = self._sale_price(info)
        confirm = discord.ui.Button(
            label=f"\u2705 Confirm: {info['name']} for {sale_px}\U0001fa99",
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
        sale_px = self._sale_price(info)
        if balance < sale_px:
            await interaction.response.edit_message(
                content=None,
                embed=discord.Embed(
                    title="\u274c Insufficient Coins",
                    description=f"You need **{sale_px}\U0001fa99** but only have **{balance}\U0001fa99**.",
                    color=discord.Color.red()
                ),
                view=self,
            )
            return
        self._build_confirmation(key, info)
        desc = f"**Item:** {info['emoji']} {info['name']}\n"
        if sale_px < info["cost"]:
            desc += f"**Cost:** ~~{info['cost']}\U0001fa99~~ **{sale_px}\U0001fa99** \U0001f525\n"
        else:
            desc += f"**Cost:** {info['cost']}\U0001fa99\n"
        desc += f"**Your balance:** {balance}\U0001fa99"
        embed = discord.Embed(
            title="\u2705 Confirm Purchase",
            description=desc,
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
        sale_px = self._sale_price(info)
        success = storage.spend_coins(self.guild_id, self.user_id, sale_px)
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
        storage = self.cog._get_storage()
        self.discounts = compute_item_discounts(storage, self.guild_id) if storage else {}
        self.sale_active = bool(self.discounts)
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
        try:
            asyncio.get_running_loop()
            self.event_notifier.start()
        except RuntimeError:
            pass

    def cog_unload(self):
        try:
            self.event_notifier.cancel()
        except Exception:
            pass

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
        storage = self._get_storage()
        discount = get_shop_discount(storage, guild_id) if storage else 0.0
        has_sale = discount > 0.0
        desc = f"**Your balance:** {balance}\U0001fa99\n\n"
        if has_sale:
            max_pct = round(discount * 100)
            desc = f"\U0001f525 **SALE ACTIVE — Giảm đến {max_pct}%!**\n\n" + desc
        desc += "Select a category below to browse items.\nAll purchases reset at the end of each month."
        embed = discord.Embed(
            title="\U0001fa99 Beanie Shop",
            description=desc,
            color=discord.Color.red() if has_sale else discord.Color.blue()
        )
        embed.set_footer(text="Coins carry over between months | Click an item to buy")
        if has_sale:
            for ev in get_active_events(storage, guild_id) if storage else []:
                pct = round(ev.get("discount", 0) * 100)
                label = ev.get("label", "")
                if pct > 0:
                    embed.add_field(
                        name=f"\U0001f525 {label}",
                        value=f"Giảm **{pct}%** + x{ev.get('mult', 1.0)} Coin",
                        inline=False,
                    )
        return embed

    def _build_category_embed(self, guild_id, user_id, category):
        meta = CATEGORY_META.get(category, {})
        balance = self.get_balance(guild_id, user_id)
        storage = self._get_storage()
        discount = get_shop_discount(storage, guild_id) if storage else 0.0
        has_sale = discount > 0.0
        desc = f"**Your balance:** {balance}\U0001fa99\n\n"
        if has_sale:
            desc = "\U0001f525 **SALE ACTIVE**\n\n" + desc
        desc += "Click any item to purchase.\n*All purchases reset at month end.*"
        embed = discord.Embed(
            title=f"{meta.get('emoji', '')} {meta.get('label', category)}",
            description=desc,
            color=discord.Color.red() if has_sale else discord.Color.blue()
        )
        items = ITEMS_BY_CATEGORY.get(category, {})
        for key, info in items.items():
            if has_sale:
                discounted = round(info["cost"] * (1 - discount))
                val = f"Cost: ~~{info['cost']}\U0001fa99~~ **{discounted}\U0001fa99** \U0001f525"
            else:
                val = f"Cost: **{info['cost']}\U0001fa99**"
            embed.add_field(
                name=f"{info['emoji']} {info['name']}",
                value=val,
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

        event_mult = get_coin_multiplier(storage, guild_id) if storage else 1.0
        if event_mult > 1.0:
            active_events = get_active_events(storage, guild_id) if storage else []
            labels = ", ".join(ev.get("label", "") for ev in active_events if ev.get("mult", 1.0) > 1.0)
            embed.add_field(
                name="\U0001f525 Event Active!",
                value=f"x{event_mult} Coin Earnings\n{labels}",
                inline=False,
            )

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

    # ── Event Notifier Loop ──────────────────────────────────────────────

    @tasks.loop(minutes=5)
    async def event_notifier(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.UTC)
        now_iso = now.isoformat()
        for guild in self.bot.guilds:
            try:
                guild_config = self.config.get_guild_config(guild.id)
                patch_channel_id = guild_config.get_patch_notes_channel_id()
                if not patch_channel_id:
                    continue
                channel = guild.get_channel(patch_channel_id)
                if not channel:
                    continue

                storage = self._get_storage()
                if not storage:
                    continue

                current_ids = {ev["id"] for ev in get_active_events(storage, guild.id, now)}
                if not current_ids:
                    continue

                state = storage.get_guild_state(guild.id, "last_event_ids") or []
                previous_ids = set(state)

                started = current_ids - previous_ids
                ended = previous_ids - current_ids

                if started:
                    for ev in get_active_events(storage, guild.id, now):
                        if ev["id"] in started:
                            pct = round(ev.get("discount", 0) * 100)
                            mult = ev.get("mult", 1.0)
                            label = ev.get("label", "")
                            embed = discord.Embed(
                                title=f"\U0001f389 Sự Kiện Bắt Đầu: {label}",
                                color=discord.Color.green(),
                            )
                            parts = []
                            if pct > 0:
                                parts.append(f"Giảm **{pct}%** cho tất cả item trong shop")
                            if mult > 1.0:
                                parts.append(f"x{mult} Coin khi ở trong voice")
                            embed.description = "\n".join(parts)
                            embed.set_footer(text="Sự kiện kết thúc lúc 23:59 hôm nay (GMT+7)")
                            try:
                                await channel.send(embed=embed)
                            except Exception:
                                pass

                if ended:
                    for ev_id in ended:
                        ev_info = next((e for e in BUILTIN_EVENTS + [{"id": "lunar_new_year", "label": "Tết Nguyên Đán", "discount": 0.4, "mult": 2.0}] if e["id"] == ev_id), None)
                        if ev_info:
                            embed = discord.Embed(
                                title=f"\u2705 Sự Kiện Kết Thúc: {ev_info['label']}",
                                description="Hẹn gặp lại bạn trong sự kiện lần sau!",
                                color=discord.Color.light_gray(),
                            )
                            try:
                                await channel.send(embed=embed)
                            except Exception:
                                pass

                storage.set_guild_state(guild.id, "last_event_ids", list(current_ids))
            except Exception:
                pass

    @event_notifier.before_loop
    async def before_event_notifier(self):
        await self.bot.wait_until_ready()

    # ── Event Admin Commands ─────────────────────────────────────────────

    event_group = app_commands.Group(name="event", description="Manage economy events")

    @event_group.command(name="create", description="Create a custom event for this guild")
    @app_commands.describe(
        event_type="Type: coin_multiplier, shop_discount, or both",
        value="Multiplier (e.g. 2.0) or discount fraction (e.g. 0.3 for 30%)",
        duration_hours="How long the event lasts in hours",
        reason="Short description shown to users",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def event_create_cmd(self, interaction: discord.Interaction,
                                event_type: str,
                                value: float,
                                duration_hours: int,
                                reason: str = ""):
        await interaction.response.defer(ephemeral=True)
        if event_type not in ("coin_multiplier", "shop_discount", "both"):
            await interaction.followup.send("\u274c event_type must be: coin_multiplier, shop_discount, or both")
            return
        if value <= 0:
            await interaction.followup.send("\u274c Value must be positive")
            return
        if duration_hours < 1 or duration_hours > 168:
            await interaction.followup.send("\u274c Duration must be between 1 and 168 hours")
            return

        storage = self._get_storage()
        if not storage:
            await interaction.followup.send("\u274c Economy system unavailable")
            return

        now = datetime.now(timezone.UTC)
        starts_at = now.isoformat()
        ends_at = now.replace(hour=23, minute=59, second=59).isoformat() if duration_hours >= 24 else \
            datetime.fromtimestamp(now.timestamp() + duration_hours * 3600, tz=timezone.UTC).isoformat()

        scope = "all"
        event_id = storage.add_event(interaction.guild.id, event_type, scope, value, starts_at, ends_at, reason)

        pct = round(value * 100) if event_type in ("shop_discount", "both") else None
        mult = value if event_type in ("coin_multiplier", "both") else None
        desc_parts = []
        if mult:
            desc_parts.append(f"x{mult} Coin Earnings")
        if pct:
            desc_parts.append(f"{pct}% Off Shop")
        await interaction.followup.send(
            f"\u2705 Event created! ({', '.join(desc_parts)})\n"
            f"Duration: {duration_hours}h\n"
            f"Reason: {reason or 'N/A'}",
        )

    @event_group.command(name="end", description="End all active custom events for this guild")
    @app_commands.checks.has_permissions(administrator=True)
    async def event_end_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        storage = self._get_storage()
        if not storage:
            await interaction.followup.send("\u274c Economy system unavailable")
            return
        storage.deactivate_guild_events(interaction.guild.id)
        await interaction.followup.send("\u2705 All custom events ended for this guild.")

    @event_group.command(name="list", description="Show active events for this guild")
    async def event_list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        storage = self._get_storage()
        if not storage:
            await interaction.followup.send("\u274c Economy system unavailable")
            return
        active = get_active_events(storage, interaction.guild.id)
        if not active:
            await interaction.followup.send("No active events.")
            return
        lines = []
        for ev in active:
            pct = round(ev.get("discount", 0) * 100)
            mult = ev.get("mult", 1.0)
            label = ev.get("label", ev.get("reason", "Unknown"))
            source = "Global" if not ev.get("_custom") else "Custom"
            lines.append(f"\U0001f539 **{label}** ({source})")
            if pct > 0:
                lines.append(f"   Giảm {pct}%")
            if mult > 1.0:
                lines.append(f"   x{mult} Coin")
        embed = discord.Embed(
            title="\U0001f525 Active Events",
            description="\n".join(lines) if lines else "None",
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed)
