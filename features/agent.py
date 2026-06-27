"""Agent tools and system prompt for Beanie Bot AI."""

import logging
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
            "name": "shop_list",
            "description": "Xem danh sách các item có thể mua trong shop",
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
                        "description": "Số coin muốn gửi"
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
    "- leaderboard: Xem bảng xếp hạng\n"
    "- shop_list: Xem danh sách item trong shop\n"
    "- check_server_status: Kiểm tra Minecraft server\n"
    "- gift_coins: Tặng coin cho người khác (có 2 tham số: recipient và amount)\n\n"
    "KHI NÀO DÙNG TOOL:\n"
    "- Khi người dùng hỏi về rank, coin, leaderboard, shop, server — hãy gọi tool tương ứng\n"
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
            account = storage.get_economy_account(user_id, guild_id)
            balance = account["coins"] if account else 0
            return f"Bạn đang có **{balance:.1f} 🪙** trong tài khoản."

        elif tool_name == "check_rank":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
            stats = storage.get_voice_stats(user_id, guild_id)
            total_seconds = stats.get("total_seconds", 0) if stats else 0
            hours = total_seconds / 3600
            rank_name = "Unranked"
            if voice_feature:
                rank_name = voice_feature.get_user_rank(user_id, guild_id)
            return f"Bạn đang **{rank_name}** với **{hours:.1f} giờ** voice chat."

        elif tool_name == "leaderboard":
            if storage is None:
                return "Hệ thống chưa sẵn sàng, thử lại sau nhé!"
            leaders = storage.get_voice_leaderboard(guild_id, limit=10)
            if not leaders:
                return "Chưa có ai trong bảng xếp hạng cả."
            lines = ["**Bảng xếp hạng voice:**"]
            for i, (uid, seconds) in enumerate(leaders, 1):
                member = channel.guild.get_member(uid) if channel else None
                name = member.display_name if member else f"<@{uid}>"
                hours = seconds / 3600
                lines.append(f"{i}. **{name}** — {hours:.1f}h")
            return "\n".join(lines)

        elif tool_name == "shop_list":
            if economy_feature is None:
                return "Tính năng shop chưa sẵn sàng."
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

        elif tool_name == "check_server_status":
            if minecraft_feature is None:
                return "Tính năng Minecraft chưa được cài đặt."
            try:
                embed = await minecraft_feature._build_status_embed()
                text = ""
                for field in embed.fields:
                    text += f"**{field.name}:** {field.value}\n"
                return text.strip() if text else "Không thể lấy thông tin server."
            except Exception as e:
                return f"Lỗi kiểm tra server: {e}"

        elif tool_name == "gift_coins":
            if storage is None or economy_feature is None:
                return "Hệ thống chưa sẵn sàng."
            recipient_str = tool_args.get("recipient", "")
            amount = tool_args.get("amount", 0)
            if amount <= 0:
                return "Số coin phải lớn hơn 0!"
            # Resolve recipient from the guild
            guild = channel.guild if channel else None
            recipient_member = None
            if guild:
                # Try by mention first
                for member in guild.members:
                    if member.mention == recipient_str or f"<@{member.id}>" == recipient_str:
                        recipient_member = member
                        break
                if not recipient_member:
                    # Try by display_name
                    for member in guild.members:
                        if member.display_name.lower() == recipient_str.lower():
                            recipient_member = member
                            break
                if not recipient_member:
                    # Try by name
                    for member in guild.members:
                        if member.name.lower() == recipient_str.lower():
                            recipient_member = member
                            break
            if not recipient_member:
                return f"Không tìm thấy người dùng '{recipient_str}' trong server."
            # Check sender balance
            account = storage.get_economy_account(user_id, guild_id)
            balance = account["coins"] if account else 0
            if balance < amount:
                return f"Bạn chỉ có {balance:.1f}🪙, không đủ để gửi {amount}🪙."
            # Execute transfer
            success = economy_feature._transfer_coins(user_id, recipient_member.id, guild_id, amount, storage)
            if success:
                return f"Đã gửi **{amount}🪙** cho **{recipient_member.display_name}** thành công!"
            return "Gửi coin thất bại, thử lại sau."

        else:
            return f"Tool '{tool_name}' chưa được hỗ trợ."

    except Exception as e:
        logging.error(f"Agent tool '{tool_name}' error: {e}", exc_info=True)
        return f"Có lỗi xảy ra khi thực hiện '{tool_name}': {e}"
