import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_settings, update_guild_settings
from config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR
from permissions import require_permission

logger = logging.getLogger("bot.autorole")

class AutoRole(commands.Cog):
    """Модуль автоматической выдачи роли новым участникам"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = await get_guild_settings(member.guild.id)
        if not settings.get("autorole_enabled"):
            return

        role_id = settings.get("autorole_id")
        if not role_id:
            return

        role = member.guild.get_role(role_id)
        if not role:
            logger.warning(f"Роль авто-выдачи {role_id} не найдена на сервере {member.guild.name}")
            return

        try:
            await member.add_roles(role, reason="Авто-роль при первом входе")
            logger.info(f"Выдана авто-роль {role.name} участнику {member} на сервере {member.guild.name}")
        except discord.Forbidden:
            logger.error(f"Недостаточно прав для выдачи роли {role.name} на сервере {member.guild.name}. Убедитесь, что роль бота выше выдаваемой роли.")
        except Exception as e:
            logger.error(f"Ошибка при выдаче авто-роли: {e}")

    # --- Slash Commands ---
    autorole_group = app_commands.Group(
        name="autorole",
        description="Настройка автоматической выдачи роли новым участникам"
    )

    @autorole_group.command(name="set", description="Установить роль для новых участников")
    @app_commands.describe(role="Роль, которая будет выдаваться автоматически при входе")
    async def autorole_set(self, interaction: discord.Interaction, role: discord.Role):
        if not await require_permission(interaction, "settings"):
            return
        # Проверка иерархии ролей бота
        bot_member = interaction.guild.me
        if role >= bot_member.top_role:
            embed = discord.Embed(
                title="❌ Ошибка иерархии ролей",
                description=f"Роль {role.mention} находится выше или наравне с высшей ролью бота ({bot_member.top_role.mention}).\n"
                            f"Переместите роль бота выше роли {role.mention} в настройках сервера.",
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await update_guild_settings(
            interaction.guild.id,
            autorole_enabled=1,
            autorole_id=role.id
        )

        embed = discord.Embed(
            title="✅ Авто-роль успешно настроена",
            description=f"Новым участникам теперь будет автоматически выдаваться роль: {role.mention}\nСтатус: **Включено**",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autorole_group.command(name="disable", description="Отключить автоматическую выдачу ролей")
    async def autorole_disable(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        await update_guild_settings(interaction.guild.id, autorole_enabled=0)
        embed = discord.Embed(
            title="⚙️ Авто-роль отключена",
            description="Автоматическая выдача ролей новым участникам выключена.",
            color=COLOR_PRIMARY
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autorole_group.command(name="status", description="Проверить статус авто-роли")
    async def autorole_status(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        settings = await get_guild_settings(interaction.guild.id)
        enabled = bool(settings.get("autorole_enabled"))
        role_id = settings.get("autorole_id")
        role = interaction.guild.get_role(role_id) if role_id else None

        embed = discord.Embed(
            title="👤 Статус авто-роли",
            color=COLOR_PRIMARY
        )
        embed.add_field(name="Состояние", value="🟢 Включено" if enabled else "🔴 Выключено", inline=True)
        embed.add_field(name="Назначенная роль", value=role.mention if role else "Не установлена", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
