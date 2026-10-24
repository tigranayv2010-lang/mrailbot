import discord
from typing import Dict, Any, List
from database import get_category_roles
from config import COLOR_ERROR

CATEGORIES: Dict[str, Dict[str, Any]] = {
    "moderation": {
        "name": "Модерация",
        "title": "🔨 Команды модерации",
        "description": "Команды: `/kick`, `/ban`, `/unban`, `/mute`, `/unmute`, `/clear`, `/warn`, `/warns`, `/unwarn`, `/slowmode`, `/lock`, `/unlock`",
        "default_hint": "Права Администратора или Модератора (Kick/Ban/Timeout)"
    },
    "tickets": {
        "name": "Тикеты",
        "title": "🎫 Управление тикетами",
        "description": "Команды: `/ticket setup`, `/ticket close`, `/ticket add`, `/ticket remove`",
        "default_hint": "Права Управление каналами или Администратор"
    },
    "embeds": {
        "name": "Embed Конструктор",
        "title": "🎨 Создание Embed-сообщений",
        "description": "Команды: `/embed builder`, `/embed send`, `/embed screenshot_preset`, `/embed json_send`",
        "default_hint": "Права Управление сообщениями или Администратор"
    },
    "settings": {
        "name": "Настройки сервера",
        "title": "⚙️ Настройки (Велкамер, Автороль, Верификация)",
        "description": "Команды: `/welcome`, `/autorole`, `/verify`",
        "default_hint": "Права Администратора"
    },
    "panel": {
        "name": "Главная Панель",
        "title": "🎛️ Доступ к панели /panel",
        "description": "Главный пульт управления ботом и сервером `/panel`",
        "default_hint": "Права Администратора"
    }
}

async def check_permission(interaction: discord.Interaction, category: str) -> bool:
    """Проверка прав пользователя на использование команды указанной категории"""
    if not interaction.guild:
        return False

    # Владелец сервера всегда имеет полный доступ
    if interaction.user.id == interaction.guild.owner_id:
        return True

    # Администратор сервера всегда имеет полный доступ
    if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator:
        return True

    allowed_roles = await get_category_roles(interaction.guild.id, category)

    # Если для категории не заданы кастомные роли — действуют стандартные права Discord
    if not allowed_roles:
        perms = interaction.user.guild_permissions if isinstance(interaction.user, discord.Member) else None
        if not perms:
            return False
        if category == "moderation":
            return perms.kick_members or perms.ban_members or perms.moderate_members or perms.manage_messages
        if category == "embeds":
            return perms.manage_messages
        if category == "tickets":
            return perms.manage_channels
        if category in ("settings", "panel"):
            return perms.administrator or perms.manage_guild
        return False

    # Если роли настроены — проверяем наличие хотя бы одной у участника
    if isinstance(interaction.user, discord.Member):
        user_role_ids = {r.id for r in interaction.user.roles}
        return any(rid in user_role_ids for rid in allowed_roles)

    return False

async def require_permission(interaction: discord.Interaction, category: str) -> bool:
    """
    Проверяет права. Если прав нет — отправляет понятное ephemeral сообщение
    с перечнем требуемых ролей и возвращает False.
    """
    has_perm = await check_permission(interaction, category)
    if not has_perm:
        allowed_roles = await get_category_roles(interaction.guild.id, category)
        info = CATEGORIES.get(category, {"title": category, "default_hint": "Администратор"})

        if allowed_roles:
            role_mentions = ", ".join([f"<@&{rid}>" for rid in allowed_roles])
            desc = (
                f"🚫 **У вас нет доступа к командам из категории «{info.get('title')}»**\n\n"
                f"Для использования требуется наличие одной из ролей:\n{role_mentions}\n\n"
                f"*Либо права Администратора сервера.*"
            )
        else:
            desc = (
                f"🚫 **У вас недостаточно прав для использования «{info.get('title')}»**\n\n"
                f"Требуемые права: *{info.get('default_hint')}*."
            )

        embed = discord.Embed(
            title="Отказано в доступе",
            description=desc,
            color=COLOR_ERROR
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return True
