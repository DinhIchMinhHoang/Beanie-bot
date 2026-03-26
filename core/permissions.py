"""
Permission checking utilities for Beanie Bot.
Provides decorators and functions for role-based access control.
"""

import discord
from discord import app_commands
from typing import Callable
import logging


def admin_only():
    """
    Decorator for slash commands requiring admin permission.
    
    Usage:
        @app_commands.command(name='test')
        @admin_only()
        async def test_command(self, interaction: discord.Interaction):
            pass
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ This command requires Administrator permission.",
                ephemeral=True
            )
            logging.warning(f"Permission denied for {interaction.user} ({interaction.user.id}) on command")
            return False
        return True
    
    return app_commands.check(predicate)


def guild_admin_or_self(target_user_param: str = "user"):
    """
    Decorator allowing admin to perform actions on anyone,
    but regular users only on themselves.
    
    Args:
        target_user_param: Name of the user parameter in the command
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        is_admin = interaction.user.guild_permissions.administrator
        
        if is_admin:
            return True
        
        # Non-admin can only target themselves
        target_user = interaction.namespace.user if hasattr(interaction.namespace, target_user_param) else None
        
        if target_user and target_user.id != interaction.user.id:
            await interaction.response.send_message(
                "❌ You can only perform actions on yourself. Use the command without specifying a user.",
                ephemeral=True
            )
            logging.warning(f"Permission denied for {interaction.user}: attempted to modify other user")
            return False
        
        return True
    
    return app_commands.check(predicate)


def is_guild_owner():
    """Decorator for commands requiring guild owner permission."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can use this command.",
                ephemeral=True
            )
            return False
        return True
    
    return app_commands.check(predicate)


def has_role(role_id: int):
    """Decorator for commands requiring a specific role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        
        if not any(role.id == role_id for role in interaction.user.roles):
            role = interaction.guild.get_role(role_id)
            role_name = role.name if role else f"Role {role_id}"
            await interaction.response.send_message(
                f"❌ You need the {role_name} role to use this command.",
                ephemeral=True
            )
            return False
        
        return True
    
    return app_commands.check(predicate)
