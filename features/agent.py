"""Agent tools and system prompt for Beanie Bot AI."""

import json
import logging
import re
import asyncio
import discord

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
            "name": "leaderboard",
            "description": "Xem bảng xếp hạng voice của server (top người dùng)",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "richest",
            "description": "Xem bảng xếp hạng coin của server (top người giàu nhất)",
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
            "name": "check_birthdays",
            "description": "Xem danh sách sinh nhật đã đăng ký trong server",
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
            "name": "gift_coins",
            "description": "Tặng coin cho người dùng khác. Tham số recipient là tên hoặc mention, amount là số coin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Tên người nhận coin (display name hoặc mention)"
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
]

SYSTEM_PROMPT = (
    "Bạn là Beanie, một thanh niên Việt Nam chất chơi, hài hước, lém lỉnh, biết trêu chọc, khen ngợi, và luôn làm theo yêu cầu của người dùng. "
    "Hãy trả lời như một người bạn thân, có thể pha trò, chọc nhẹ, khen ngợi, hoặc chửi vui vẻ nhưng không xúc phạm. Trả lời ngắn gọn và dứt khoát. "
    "Đừng bắt đầu câu trả lời với 'Ulatr!' hoặc bất kỳ từ cảm thán nào quá thường xuyên. Hãy đa dạng cách diễn đạt và chỉ dùng icon hoặc biểu tượng khi thật sự phù hợp, không phải lúc nào cũng cần. "
    "Luôn giữ sự hài hước, dí dỏm, và phong cách 'dope' của giới trẻ Việt Nam. "
    "Nếu người dùng hỏi bằng tiếng Anh, hãy trả lời bằng tiếng Anh với phong cách tương tự. Nếu hỏi bằng tiếng Việt, hãy trả lời bằng tiếng Việt. "
    "Nếu không chắc ngôn ngữ, hãy ưu tiên tiếng Việt. Không được trả lời quá lịch sự hoặc quá máy móc.\n\n"
    "BẠN CÓ CÁC CÔNG CỤ SAU:\n"
    "- check_economy: Xem số dư coin của người dùng\n"
    "- check_rank: Xem hạng voice của người dùng\n"
    "- leaderboard: Xem bảng xếp hạng voice\n"
    "- richest: Xem bảng xếp hạng coin\n"
    "- shop_list: Xem danh sách item trong shop\n"
    "- check_birthdays: Xem danh sách sinh nhật\n"
    "- check_server_status: Kiểm tra Minecraft server\n"
    "- gift_coins: Tặng coin cho người khác (có 2 tham số: recipient và amount)\n\n"
    "KHI NÀO DÙNG TOOL:\n"
    "- Khi người dùng hỏi về rank, coin, leaderboard, shop, birthday, server — hãy gọi tool tương ứng\n"
    "- Khi người dùng muốn tặng coin — dùng gift_coins với recipient (tên người dùng) và amount (số coin)\n"
    "- Nếu chỉ chat bình thường (hỏi thăm, tán gẫu) — KHÔNG cần gọi tool, trả lời tự nhiên\n"
    "- Nếu không chắc có tool phù hợp hay không — cứ trả lời tự nhiên, đừng bịa tool"
)


def build_messages(memory, current_text, max_context=60):
    """Build OpenAI messages array from memory + current user text."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    recent = memory[-max_context:] if len(memory) > max_context else memory
    for m in recent:
        msg = {"role": m["role"]}
        if "content" in m:
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
        if tool_name == "check_economy":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
            balance = storage.get_balance(guild_id, user_id)
            return f"Bạn đang có **{balance:.1f} 🪙** trong tài khoản."

        elif tool_name == "check_rank":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
            stats = storage.load_voice_stats(guild_id)
            total_seconds = stats.get(str(user_id), 0)
            hours = total_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(hours)[0]
            return f"Bạn đang **{rank_name}** với **{hours:.1f} giờ** voice chat."

        elif tool_name == "leaderboard":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
            all_time = storage.load_all_time_voice_stats(guild_id)
            if not all_time:
                return "Chưa có ai trong bảng xếp hạng voice cả."
            sorted_users = sorted(all_time.items(), key=lambda x: x[1], reverse=True)[:10]
            lines = ["**Bảng xếp hạng voice:**"]
            for i, (uid_str, seconds) in enumerate(sorted_users, 1):
                uid = int(uid_str)
                member = channel.guild.get_member(uid) if channel else None
                name = member.display_name if member else f"<@{uid}>"
                hours = seconds / 3600
                lines.append(f"{i}. **{name}** — {hours:.1f}h")
            return "\n".join(lines)

        elif tool_name == "richest":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
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
            for item in SHOP_ITEMS:
                price_icon = item.get("emoji", "🪙")
                lines.append(f"- {price_icon} **{item['name']}** — {item['price']}🪙")
                if item.get("description"):
                    lines.append(f"  _{item['description']}_")
            return "\n".join(lines)

        elif tool_name == "check_birthdays":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
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
                    from mcrcon import MCRcon
                    try:
                        with MCRcon(
                            minecraft_feature.config.RCON_HOST,
                            minecraft_feature.config.RCON_PASSWORD,
                            port=minecraft_feature.config.RCON_PORT,
                        ) as mcr:
                            out = mcr.command("list")
                        m = re.search(r"There are (\d+) of a max", out)
                        if m:
                            parts.append(f"🟢 Minecraft (RCON): {m.group(1)} players")
                        else:
                            parts.append("🟡 Minecraft (RCON): OK (không parse được player)")
                    except Exception:
                        parts.append("⚫ Minecraft (RCON): Không kết nối được")
                else:
                    parts.append("⚫ Minecraft: VM chưa chạy hoặc RCON chưa bật")
            except Exception:
                parts.append("⚫ Minecraft: Không xác định")
            return "\n".join(parts) if parts else "Không có thông tin server."

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
            recipient_member = None
            if guild:
                for member in guild.members:
                    if member.mention == recipient_str or f"<@{member.id}>" == recipient_str:
                        recipient_member = member
                        break
                if not recipient_member:
                    for member in guild.members:
                        if member.display_name.lower() == recipient_str.lower():
                            recipient_member = member
                            break
                if not recipient_member:
                    for member in guild.members:
                        if member.name.lower() == recipient_str.lower():
                            recipient_member = member
                            break
            if not recipient_member:
                return f"Không tìm thấy người dùng '{recipient_str}' trong server."
            if recipient_member.id == user_id:
                return "Không thể tặng coin cho chính mình!"
            balance = storage.get_balance(guild_id, user_id)
            tax = int(amount * 0.1)
            total_deduct = amount + tax
            if balance < total_deduct:
                return f"Bạn chỉ có {balance:.1f}🪙, cần {total_deduct}🪙 (gồm {tax}🪙 thuế) để gửi {amount}🪙."
            success = storage.spend_coins(guild_id, user_id, total_deduct)
            if not success:
                return "Giao dịch thất bại, thử lại sau."
            storage.add_coins(guild_id, recipient_member.id, float(amount))
            sender_new = storage.get_balance(guild_id, user_id)
            return (
                f"Đã gửi **{amount}🪙** cho **{recipient_member.display_name}** thành công! "
                f"(Thuế: {tax}🪙)\nSố dư mới của bạn: {sender_new:.1f}🪙"
            )

        else:
            return f"Tool '{tool_name}' chưa được hỗ trợ."

    except Exception as e:
        logging.error(f"Agent tool '{tool_name}' error: {e}", exc_info=True)
        return f"Có lỗi xảy ra khi thực hiện '{tool_name}': {e}"
