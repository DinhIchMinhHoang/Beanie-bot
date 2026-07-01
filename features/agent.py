"""Agent tools and system prompt for Beanie Bot AI."""

import json
import logging
import re
import asyncio
from datetime import datetime

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_economy",
            "description": "Xem số dư coin của người dùng",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_rank",
            "description": "Xem hạng voice và tổng số giờ chat của người dùng",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_user_rank",
            "description": "Xem hạng voice và số giờ của một người dùng bất kỳ (cần tên)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Tên hoặc mention của người dùng"
                    }
                },
                "required": ["name"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "leaderboard",
            "description": "Xem bảng xếp hạng voice của server",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "richest",
            "description": "Xem bảng xếp hạng coin của server",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_voice_stats",
            "description": "Xem chi tiết số giờ voice của bản thân (tháng này + tổng)",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_help",
            "description": "Xem các cấp bậc voice và quyền lợi tương ứng",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "join_competition",
            "description": "Tham gia cuộc thi voice tracking",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_competition",
            "description": "Rời khỏi cuộc thi voice tracking",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shop_list",
            "description": "Xem danh sách các item có thể mua trong shop",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buy_item",
            "description": "Mua một item từ shop (gọi shop_list trước để xem tên item)",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Tên item muốn mua (vd: '1 Hour', '50 Hours', '+100KB Sound')"
                    }
                },
                "required": ["item_name"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_purchases",
            "description": "Xem lịch sử mua hàng trong tháng của bản thân",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gift_coins",
            "description": "Tặng coin cho người dùng khác",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Tên hoặc mention người nhận"
                    },
                    "amount": {
                        "type": "number",
                        "description": "Số coin muốn gửi (tối thiểu 10)"
                    }
                },
                "required": ["recipient", "amount"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_birthdays",
            "description": "Xem danh sách sinh nhật đã đăng ký trong server",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "next_birthday",
            "description": "Xem sinh nhật sắp tới gần nhất",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_birthday",
            "description": "Đăng ký sinh nhật cho bản thân (định dạng dd/mm)",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Ngày sinh định dạng dd/mm (vd: 25/12)"
                    }
                },
                "required": ["date"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "active_events",
            "description": "Xem các sự kiện đang diễn ra trong server",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "event_calendar",
            "description": "Xem lịch sự kiện cả năm",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "channel_hours",
            "description": "Xem tổng số giờ hoạt động của các kênh voice được theo dõi",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "channel_stats",
            "description": "Xem chi tiết giờ hoạt động của một kênh voice cụ thể",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Tên kênh voice muốn xem"
                    }
                },
                "required": ["name"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_server_status",
            "description": "Kiểm tra trạng thái Minecraft server và Azure VM",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_mc_command",
            "description": "Gửi lệnh điều khiển tới Minecraft server (vd: list, op, gamemode, time, weather, tp, give)",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Lệnh Minecraft cần thực thi (không bao gồm dấu /)"
                    }
                },
                "required": ["command"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_info",
            "description": "Xem nhanh thông tin cá nhân (coin + rank + giờ voice)",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "help_tools",
            "description": "Xem danh sách tất cả công cụ Beanie có thể dùng",
        },
    },
]

SYSTEM_PROMPT = (
    "Bạn là Beanie, một thanh niên Việt Nam chất chơi, hài hước, lém lỉnh, biết trêu chọc, khen ngợi, và luôn làm theo yêu cầu của người dùng. "
    "Hãy trả lời như một người bạn thân, có thể pha trò, chọc nhẹ, khen ngợi, hoặc chửi vui vẻ nhưng không xúc phạm. Trả lời ngắn gọn và dứt khoát. "
    "Đừng bắt đầu câu trả lời với 'Ulatr!' hoặc bất kỳ từ cảm thán nào quá thường xuyên. Hãy đa dạng cách diễn đạt và chỉ dùng icon hoặc biểu tượng khi thật sự phù hợp, không phải lúc nào cũng cần. "
    "Luôn giữ sự hài hước, dí dỏm, và phong cách 'dope' của giới trẻ Việt Nam. "
    "Nếu người dùng hỏi bằng tiếng Anh, hãy trả lời bằng tiếng Anh với phong cách tương tự. Nếu hỏi bằng tiếng Việt, hãy trả lời bằng tiếng Việt. "
    "Nếu không chắc ngôn ngữ, hãy ưu tiên tiếng Việt. Không được trả lời quá lịch sự hoặc quá máy móc.\n\n"
    "BẠN CÓ CÁC CÔNG CỤ SAU:\n"
    "💰 Economy: check_economy, richest, shop_list, buy_item, my_purchases, gift_coins\n"
    "🎤 Voice: check_rank, check_user_rank [tên], leaderboard, my_voice_stats, rank_help, join_competition, remove_competition\n"
    "🎂 Birthday: check_birthdays, next_birthday, add_birthday [dd/mm]\n"
    "📅 Events: active_events, event_calendar\n"
    "📊 Channel: channel_hours, channel_stats [tên]\n"
    "🎮 Minecraft: check_server_status, execute_mc_command [lệnh]\n"
    "📋 Chung: my_info, help_tools\n\n"
    "QUY TẮC:\n"
    "- Khi người dùng hỏi về thông tin cá nhân (coin, rank, giờ) — dùng my_info\n"
    "- Khi hỏi về rank của người khác — dùng check_user_rank với tên\n"
    "- Khi muốn mua item — dùng buy_item với tên item chính xác\n"
    "- Khi muốn tặng coin — dùng gift_coins\n"
    "- Khi muốn tham gia voice tracking — dùng join_competition\n"
    "- Khi muốn gửi lệnh điều khiển Minecraft — dùng execute_mc_command với lệnh (vd: 'op Bean', 'gamemode creative', 'time set day')\n"
    "- Nếu chỉ chat bình thường — không cần gọi tool, trả lời tự nhiên"
)


def _resolve_member(guild, name):
    """Resolve a member from a guild by mention, display_name, or name."""
    if not guild:
        return None
    for member in guild.members:
        if member.mention == name or f"<@{member.id}>" == name:
            return member
    for member in guild.members:
        if member.display_name.lower() == name.lower():
            return member
    for member in guild.members:
        if member.name.lower() == name.lower():
            return member
    return None


def _format_tool_list():
    lines = ["**Beanie có thể làm được những việc sau:**\n"]
    for t in TOOL_DEFINITIONS:
        fn = t["function"]
        params = ""
        if "parameters" in fn and "properties" in fn["parameters"]:
            required = fn["parameters"].get("required", [])
            props = fn["parameters"]["properties"]
            param_strs = [f"[{p}]" for p in props]
            params = " " + " ".join(param_strs)
        lines.append(f"• `{fn['name']}{params}` — {fn['description']}")
    return "\n".join(lines)


def build_messages(memory, current_text, max_context=60):
    """Build OpenAI messages array from memory + current user text."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    recent = memory[-max_context:] if len(memory) > max_context else memory
    for m in recent:
        msg = {"role": m["role"]}
        if m["role"] == "user" and "user" in m:
            msg["content"] = f"{m['user']}: {m.get('content', '')}"
        elif "content" in m:
            msg["content"] = m["content"]
        if "tool_calls" in m:
            msg["tool_calls"] = m["tool_calls"]
        if "tool_call_id" in m:
            msg["tool_call_id"] = m["tool_call_id"]
        messages.append(msg)

    messages.append({"role": "user", "content": current_text})
    return messages


async def dispatch_tool(tool_name, tool_args, ctx):
    """Execute a tool and return a result string."""
    guild_id = ctx["guild_id"]
    user_id = ctx["user_id"]
    channel = ctx.get("channel")
    storage = ctx.get("storage")
    config = ctx.get("config")
    voice_feature = ctx.get("voice_feature")
    economy_feature = ctx.get("economy_feature")
    minecraft_feature = ctx.get("minecraft_feature")

    try:
        # ── Economy ──────────────────────────────────────────────

        if tool_name == "check_economy":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            balance = storage.get_balance(guild_id, user_id)
            return f"Bạn đang có **{balance:.1f} 🪙** trong tài khoản."

        elif tool_name == "richest":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            leaders = storage.get_coin_leaderboard(guild_id, limit=10)
            if not leaders:
                return "Chưa có ai trong bảng xếp hạng coin cả."
            lines = ["**Bảng xếp hạng coin:**"]
            for i, (uid, coins) in enumerate(leaders, 1):
                member = channel.guild.get_member(uid) if channel else None
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"{i}. **{name}** — {coins:.1f} 🪙")
            return "\n".join(lines)

        elif tool_name == "shop_list":
            from features.economy import SHOP_ITEMS
            if not SHOP_ITEMS:
                return "Shop đang trống."
            lines = ["**Cửa hàng Beanie:**"]
            for item in SHOP_ITEMS.values():
                lines.append(f"- {item['emoji']} **{item['name']}** — {item['cost']}🪙")
                if item.get("description"):
                    lines.append(f"  _{item['description']}_")
            return "\n".join(lines)

        elif tool_name == "buy_item":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            from features.economy import SHOP_ITEMS, process_purchase, compute_item_discounts
            item_name = tool_args.get("item_name", "").strip().lower()
            if not item_name:
                return "Cần cung cấp tên item. Dùng shop_list để xem danh sách."
            matched_key = None
            for key, item in SHOP_ITEMS.items():
                if item["name"].lower() == item_name or key.lower() == item_name:
                    matched_key = key
                    break
            if not matched_key:
                for key, item in SHOP_ITEMS.items():
                    if item_name in item["name"].lower() or item_name in key.lower():
                        matched_key = key
                        break
            if not matched_key:
                return f"Không tìm thấy item '{item_name}'. Dùng shop_list để xem danh sách."
            item = SHOP_ITEMS[matched_key]
            discounts = compute_item_discounts(storage, guild_id)
            success, msg, _ = process_purchase(storage, guild_id, user_id, matched_key, item, discounts, voice_feature=voice_feature)
            return msg

        elif tool_name == "my_purchases":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            month = datetime.now().strftime("%Y-%m")
            purchases = storage.get_all_purchases(guild_id, user_id, month)
            if not purchases:
                return "Bạn chưa mua gì trong tháng này."
            from features.economy import SHOP_ITEMS
            lines = [f"**Lịch sử mua hàng tháng {month}:**"]
            for ptype, pvalue in purchases.items():
                item_names = [v["name"] for v in SHOP_ITEMS.values() if v["type"] == ptype and v["value"] == pvalue]
                name = item_names[0] if item_names else f"{ptype} {pvalue}"
                lines.append(f"- **{name}** ({pvalue} {ptype})")
            return "\n".join(lines)

        elif tool_name == "gift_coins":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            recipient_str = tool_args.get("recipient", "")
            amount = tool_args.get("amount", 0)
            if amount <= 0:
                return "Số coin phải lớn hơn 0!"
            if amount < 10:
                return "Số coin tối thiểu là 10 🪙!"
            guild = channel.guild if channel else None
            recipient_member = _resolve_member(guild, recipient_str)
            if not recipient_member:
                return f"Không tìm thấy người dùng '{recipient_str}'."
            if recipient_member.id == user_id:
                return "Không thể tặng coin cho chính mình!"
            balance = storage.get_balance(guild_id, user_id)
            tax = int(amount * 0.1)
            total_deduct = amount + tax
            if balance < total_deduct:
                return f"Bạn chỉ có {balance:.1f}🪙, cần {total_deduct}🪙 (gồm {tax}🪙 thuế)."
            success = storage.spend_coins(guild_id, user_id, total_deduct)
            if not success:
                return "Giao dịch thất bại."
            storage.add_coins(guild_id, recipient_member.id, float(amount))
            sender_new = storage.get_balance(guild_id, user_id)
            return (
                f"Đã gửi **{amount}🪙** cho **{recipient_member.display_name}**! "
                f"(Thuế: {tax}🪙)\nSố dư mới: {sender_new:.1f}🪙"
            )

        # ── Voice / Rank ────────────────────────────────────────

        elif tool_name == "check_rank":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            stats = storage.load_voice_stats(guild_id)
            total_seconds = stats.get(str(user_id), 0)
            hours = total_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(hours)[0]
            return f"Bạn đang **{rank_name}** với **{hours:.1f} giờ** voice chat."

        elif tool_name == "check_user_rank":
            target_name = tool_args.get("name", "")
            if not target_name:
                return "Cần cung cấp tên người dùng."
            guild = channel.guild if channel else None
            target_member = _resolve_member(guild, target_name)
            if not target_member:
                return f"Không tìm thấy '{target_name}'."
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            stats = storage.load_voice_stats(guild_id)
            total_seconds = stats.get(str(target_member.id), 0)
            hours = total_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(hours)[0]
            return f"**{target_member.display_name}** đang **{rank_name}** với **{hours:.1f} giờ** voice chat."

        elif tool_name == "leaderboard":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            all_time = storage.load_all_time_voice_stats(guild_id)
            if not all_time:
                return "Chưa có ai trong bảng xếp hạng voice."
            sorted_users = sorted(all_time.items(), key=lambda x: x[1], reverse=True)[:10]
            lines = ["**Bảng xếp hạng voice:**"]
            for i, (uid_str, seconds) in enumerate(sorted_users, 1):
                uid = int(uid_str)
                member = channel.guild.get_member(uid) if channel else None
                name = member.display_name if member else f"<@{uid}>"
                hours = seconds / 3600
                lines.append(f"{i}. **{name}** — {hours:.1f}h")
            return "\n".join(lines)

        elif tool_name == "my_voice_stats":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            stats = storage.load_voice_stats(guild_id)
            current_seconds = stats.get(str(user_id), 0)
            all_time = storage.load_all_time_voice_stats(guild_id)
            all_seconds = all_time.get(str(user_id), 0)
            current_hours = current_seconds / 3600
            all_hours = all_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(all_hours)[0]
            return (
                f"**Thông tin voice của bạn:**\n"
                f"• Cấp bậc: **{rank_name}**\n"
                f"• Tháng này: **{current_hours:.1f}h**\n"
                f"• Tổng: **{all_hours:.1f}h**"
            )

        elif tool_name == "rank_help":
            return (
                "**Các cấp bậc voice:**\n"
                "1. 🥉 **Iron** — 0h (mặc định)\n"
                "2. 🥉 **Bronze** — 20h\n"
                "3. 🥉 **Silver** — 40h\n"
                "4. 🥈 **Gold** — 60h + `/say`\n"
                "5. 🥈 **Platinum** — 80h\n"
                "6. 💎 **Diamond** — 100h + entrance sound\n"
                "7. 💎 **Elite** — 120h\n"
                "8. 👑 **Immortal** — 140h + custom sound\n"
                "9. 👑 **Legendary** — 160h + custom sound\n\n"
                "Dùng `/beanie tham gia` để join voice tracking!"
            )

        elif tool_name == "join_competition":
            if voice_feature is None:
                return "Hệ thống voice chưa sẵn sàng."
            guild = channel.guild if channel else None
            if not guild:
                return "Không xác định được server."
            from features.voice_track import add_competitor
            member = guild.get_member(user_id)
            if not member:
                return "Không tìm thấy bạn trong server."
            success, msg = await add_competitor(voice_feature, guild, member, config)
            return msg

        elif tool_name == "remove_competition":
            if voice_feature is None:
                return "Hệ thống voice chưa sẵn sàng."
            guild = channel.guild if channel else None
            if not guild:
                return "Không xác định được server."
            from features.voice_track import remove_competitor
            member = guild.get_member(user_id)
            if not member:
                return "Không tìm thấy bạn trong server."
            success, msg = await remove_competitor(voice_feature, guild, member)
            return msg

        # ── Birthdays ────────────────────────────────────────────

        elif tool_name == "check_birthdays":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            birthdays = storage.load_birthdays(guild_id)
            if not birthdays:
                return "Chưa có ai đăng ký sinh nhật."
            lines = ["**Danh sách sinh nhật:**"]
            for uid_str, date_str in birthdays.items():
                uid = int(uid_str)
                member = channel.guild.get_member(uid) if channel else None
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"- **{name}** — {date_str}")
            return "\n".join(lines)

        elif tool_name == "next_birthday":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            birthdays = storage.load_birthdays(guild_id)
            if not birthdays:
                return "Chưa có ai đăng ký sinh nhật."
            now = datetime.now()
            today = (now.month, now.day)
            upcoming = []
            for uid_str, date_str in birthdays.items():
                try:
                    parts = date_str.split("/")
                    bday = (int(parts[1]), int(parts[0]))  # (month, day)
                except (IndexError, ValueError):
                    continue
                    diff = (bday[0] - now.month) * 30 + (bday[1] - now.day)
                if diff < 0:
                    diff += 365
                upcoming.append((diff, bday, uid_str, date_str))
            upcoming.sort()
            if not upcoming:
                return "Không có sinh nhật nào."
            uid = int(upcoming[0][3])
            member = channel.guild.get_member(uid) if channel else None
            name = member.display_name if member else f"<@{uid}>"
            return f"Sinh nhật sắp tới: **{name}** vào **{upcoming[0][4]}** ({upcoming[0][0]} ngày nữa)"

        elif tool_name == "add_birthday":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            date_str = tool_args.get("date", "")
            if not date_str:
                return "Cần cung cấp ngày sinh (định dạng dd/mm)."
            from core.validation import Validator
            is_valid, normalized_date = Validator.validate_date_ddmm(date_str)
            if not is_valid:
                return "Ngày không hợp lệ! Dùng định dạng dd/mm (vd: 25/12)."
            birthdays = storage.load_birthdays(guild_id)
            birthdays[str(user_id)] = normalized_date
            storage.save_birthdays(guild_id, birthdays)
            return f"Đã đăng ký sinh nhật **{normalized_date}** thành công! 🎂"

        # ── Events ───────────────────────────────────────────────

        elif tool_name == "active_events":
            if storage is None or config is None:
                return "Hệ thống chưa sẵn sàng."
            try:
                from features.economy import get_active_events
                now = datetime.now(config.VIETNAM_TZ) if hasattr(config, 'VIETNAM_TZ') else datetime.now()
                active = get_active_events(storage, guild_id, now)
                if not active:
                    return "Hiện tại không có sự kiện nào đang diễn ra."
                lines = ["**Sự kiện đang diễn ra:**"]
                for ev in active:
                    lines.append(f"- {ev.get('emoji', '🎉')} **{ev['name']}**: {ev['description']}")
                return "\n".join(lines)
            except Exception as e:
                return f"Lỗi lấy thông tin sự kiện: {e}"

        elif tool_name == "event_calendar":
            if storage is None or config is None:
                return "Hệ thống chưa sẵn sàng."
            try:
                from features.economy import _event_schedule_entries, BUILTIN_EVENTS
                now = datetime.now(config.VIETNAM_TZ) if hasattr(config, 'VIETNAM_TZ') else datetime.now()
                entries = _event_schedule_entries(storage, guild_id, now)
                if not entries:
                    return "Không có sự kiện nào trong năm."
                by_month = {}
                for ev in entries:
                    m = ev["starts_at"].month
                    by_month.setdefault(m, []).append(ev)
                lines = ["**Lịch sự kiện cả năm:**"]
                for month_num in sorted(by_month.keys()):
                    month_name = ["", "Th1", "Th2", "Th3", "Th4", "Th5", "Th6",
                                  "Th7", "Th8", "Th9", "Th10", "Th11", "Th12"][month_num]
                    for ev in by_month[month_num]:
                        status = "🟢" if ev["active"] else "🔒"
                        lines.append(f"{status} **{month_name}**: {ev['name']} ({ev['description']})")
                return "\n".join(lines)
            except Exception as e:
                return f"Lỗi lấy lịch sự kiện: {e}"

        # ── Channel Tracking ─────────────────────────────────────

        elif tool_name == "channel_hours":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            try:
                tracked = storage.load_tracked_channels(guild_id)
                if not tracked:
                    return "Chưa có kênh voice nào được theo dõi."
                now = datetime.now()
                period = now.strftime("%Y-%m")
                lines = ["**Giờ hoạt động kênh voice:**"]
                for ch_id in tracked:
                    ch = channel.guild.get_channel(ch_id) if channel else None
                    ch_name = ch.name if ch else f"<#{ch_id}>"
                    total = storage.load_channel_voice_stats(guild_id, ch_id, period)
                    if total > 0:
                        lines.append(f"- **{ch_name}**: {total:.1f}h tháng này")
                if len(lines) == 1:
                    return "Các kênh được theo dõi nhưng chưa có dữ liệu."
                return "\n".join(lines)
            except Exception as e:
                return f"Lỗi: {e}"

        elif tool_name == "channel_stats":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            target_name = tool_args.get("name", "").strip().lower()
            if not target_name:
                return "Cần cung cấp tên kênh."
            guild = channel.guild if channel else None
            if not guild:
                return "Không xác định server."
            tracked = storage.load_tracked_channels(guild_id)
            match_ch = None
            for ch_id in tracked:
                ch = guild.get_channel(ch_id)
                if ch and target_name in ch.name.lower():
                    match_ch = ch
                    break
            if not match_ch:
                return f"Không tìm thấy kênh '{target_name}' trong danh sách theo dõi."
            now = datetime.now()
            period = now.strftime("%Y-%m")
            total = storage.load_channel_voice_stats(guild_id, match_ch.id, period)
            all_time = 0
            try:
                all_time = storage.load_all_time_channel_stats(guild_id, match_ch.id)
            except AttributeError:
                all_time = total
            return (
                f"**📊 {match_ch.name}**\n"
                f"• Tháng này: **{total:.1f}h**\n"
                f"• Tổng: **{all_time:.1f}h**"
            )

        # ── Minecraft ────────────────────────────────────────────

        elif tool_name == "check_server_status":
            if minecraft_feature is None:
                return "Tính năng Minecraft chưa được cài đặt."
            parts = []
            try:
                if minecraft_feature.compute_client:
                    vm = minecraft_feature.compute_client.virtual_machines.get(
                        minecraft_feature.config.AZURE_RESOURCE_GROUP,
                        minecraft_feature.config.AZURE_VM_NAME,
                        expand='instanceView'
                    )
                    vm_status = vm.instance_view.statuses[1].display_status
                    parts.append(f"🖥️ Azure VM: {vm_status}")
                else:
                    parts.append("🖥️ Azure VM: Chưa cấu hình")
            except Exception as e:
                parts.append(f"🖥️ Azure VM: Lỗi — {e}")
            try:
                if (minecraft_feature.vm_is_running()
                        and minecraft_feature.config.RCON_ENABLED
                        and minecraft_feature.config.RCON_PASSWORD):
                    try:
                        out = await minecraft_feature.async_rcon_command("list", timeout=5)
                        m = re.search(r"There are (\d+) of a max", out)
                        if m:
                            parts.append(f"🟢 Minecraft (RCON): {m.group(1)} players")
                        else:
                            parts.append("🟡 Minecraft (RCON): OK")
                    except Exception:
                        parts.append("⚫ Minecraft (RCON): Không kết nối được")
                else:
                    parts.append("⚫ Minecraft: VM chưa chạy hoặc RCON chưa bật")
            except Exception:
                parts.append("⚫ Minecraft: Không xác định")
            return "\n".join(parts) if parts else "Không có thông tin server."

        elif tool_name == "execute_mc_command":
            if minecraft_feature is None:
                return "Tính năng Minecraft chưa được cài đặt."
            command = kwargs.get("command", "")
            if not command:
                return "Vui lòng nhập lệnh cần thực thi."
            try:
                if not minecraft_feature.config.RCON_ENABLED or not minecraft_feature.config.RCON_PASSWORD:
                    return "RCON chưa được cấu hình."
                out = await minecraft_feature.async_rcon_command(command, timeout=10)
                if not out or out.strip() == "":
                    return f"✅ Đã thực thi lệnh `/{command}` (không có output)."
                return f"✅ `/{command}`\n```\n{out[:1500]}\n```"
            except Exception as e:
                return f"❌ Lỗi khi thực thi lệnh: {str(e)[:300]}"

        # ── General ──────────────────────────────────────────────

        elif tool_name == "my_info":
            if storage is None:
                return "Hệ thống chưa sẵn sàng."
            balance = storage.get_balance(guild_id, user_id)
            stats = storage.load_voice_stats(guild_id)
            total_seconds = stats.get(str(user_id), 0)
            hours = total_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(hours)[0]
            return (
                f"**Thông tin của bạn:**\n"
                f"• 💰 Coin: **{balance:.1f} 🪙**\n"
                f"• 🏆 Rank: **{rank_name}**\n"
                f"• 🎤 Giờ voice: **{hours:.1f}h**\n"
                f"Dùng /beanie help để xem tôi có thể làm gì!"
            )

        elif tool_name == "help_tools":
            return _format_tool_list()

        else:
            return f"Tool '{tool_name}' chưa được hỗ trợ."

    except Exception as e:
        logging.error(f"Agent tool '{tool_name}' error: {e}", exc_info=True)
        return f"Có lỗi xảy ra khi thực hiện '{tool_name}': {e}"
