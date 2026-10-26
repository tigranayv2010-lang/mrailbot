import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_settings, update_guild_settings, parse_id_list, format_id_list
from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR
from permissions import require_permission

logger = logging.getLogger("bot.verification")

class VerifyButtonView(discord.ui.View):
    """Постоянная View с кнопкой верификации (работает даже после перезапуска бота)"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Пройти верификацию",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="persistent_verification_button"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(interaction.guild.id)
        role_ids = parse_id_list(settings.get("verify_role_ids")) or parse_id_list(settings.get("verify_role_id"))

        if not role_ids:
            return await interaction.response.send_message(
                "❌ Роли для верификации не настроены администратором сервера.",
                ephemeral=True
            )

        roles = [interaction.guild.get_role(rid) for rid in role_ids if interaction.guild.get_role(rid)]
        if not roles:
            return await interaction.response.send_message(
                "❌ Роли верификации не найдены на сервере (возможно, они были удалены).",
                ephemeral=True
            )

        member = interaction.user
        if not isinstance(member, discord.Member):
            return

        user_role_ids = {r.id for r in member.roles}
        needed_roles = [r for r in roles if r.id not in user_role_ids]

        if not needed_roles:
            return await interaction.response.send_message(
                "ℹ️ Вы уже прошли верификацию и обладаете всеми необходимыми ролями!",
                ephemeral=True
            )

        try:
            await member.add_roles(*needed_roles, reason="Верификация через кнопку")
            roles_mentions = ", ".join([r.mention for r in needed_roles])
            embed = discord.Embed(
                title="✅ Верификация пройдена!",
                description=f"Вам успешно выданы роли: {roles_mentions}.\nПриятного общения на сервере **{interaction.guild.name}**!",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Пользователь {member} прошел верификацию на сервере {interaction.guild.name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Ошибка: У бота недостаточно прав для выдачи роли. "
                "Роль бота должна быть ВЫШЕ роли верификации в списке ролей сервера.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка при верификации: {e}")
            await interaction.response.send_message("❌ Произошла непредвиденная ошибка при выдаче роли.", ephemeral=True)

class Verification(commands.Cog):
    """Модуль системы верификации на сервере"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Регистрируем постоянную View, чтобы кнопка работала после перезагрузки
        self.bot.add_view(VerifyButtonView())

    verify_group = app_commands.Group(
        name="verify",
        description="Настройка системы верификации участников"
    )

    @verify_group.command(name="setup", description="Отправить панель верификации с кнопкой")
    @app_commands.describe(
        channel="Канал, куда будет отправлено сообщение с кнопкой",
        role="Роль, которая будет выдаваться при нажатии",
        title="Заголовок сообщения верификации",
        description="Текст правил/описания верификации",
        color="Цвет боковой линии (HEX, по умолчанию #F5F3F3)"
    )
    async def verify_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        title: str = "Верификация на сервере",
        description: str = "Нажмите на кнопку **«Пройти верификацию»** ниже, чтобы подтвердить, что вы человек, и получить доступ ко всем каналам сервера!",
        color: str = "#F5F3F3"
    ):
        if not await require_permission(interaction, "settings"):
            return
        bot_member = interaction.guild.me
        if role >= bot_member.top_role:
            embed = discord.Embed(
                title="❌ Ошибка прав бота",
                description=f"Роль {role.mention} выше или равна роли бота ({bot_member.top_role.mention}).\n"
                            "Поднимите роль бота выше в настройках сервера.",
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        # Сохраняем в базу
        await update_guild_settings(
            interaction.guild.id,
            verify_enabled=1,
            verify_role_id=role.id,
            verify_role_ids=str(role.id),
            verify_channel_id=channel.id
        )

        embed = discord.Embed(
            title=title,
            description=description,
            color=parse_color(color)
        )
        embed.set_footer(
            text=f"Система защиты • {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        view = VerifyButtonView()
        try:
            await channel.send(embed=embed, view=view)
            success_embed = discord.Embed(
                title="✅ Панель верификации установлена",
                description=f"Сообщение успешно отправлено в {channel.mention}.\nРоль за верификацию: {role.mention}",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав для отправки сообщений в выбранный канал.", ephemeral=True)

    @verify_group.command(name="disable", description="Отключить систему верификации")
    async def verify_disable(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        await update_guild_settings(interaction.guild.id, verify_enabled=0)
        embed = discord.Embed(
            title="⚙️ Верификация отключена",
            description="Система верификации деактивирована.",
            color=COLOR_PRIMARY
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
