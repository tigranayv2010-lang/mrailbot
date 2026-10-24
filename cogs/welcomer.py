import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_settings, update_guild_settings
from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS
from permissions import require_permission

logger = logging.getLogger("bot.welcomer")

class Welcomer(commands.Cog):
    """Модуль приветствий (Велкамер) и прощаний"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _format_text(self, text: str, member: discord.Member) -> str:
        """Форматирование плейсхолдеров в тексте"""
        if not text:
            return ""
        return (
            text.replace("{user}", member.mention)
            .replace("{username}", member.name)
            .replace("{server}", member.guild.name)
            .replace("{count}", str(member.guild.member_count))
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await get_guild_settings(member.guild.id)
        if not settings.get("welcome_enabled"):
            return

        channel_id = settings.get("welcome_channel_id")
        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        title = self._format_text(settings.get("welcome_title") or "Добро пожаловать!", member)
        raw_msg = settings.get("welcome_message") or "Привет новенький, {user}! Добро пожаловать на сервер **{server}**!"
        description = self._format_text(raw_msg, member)
        color = parse_color(settings.get("welcome_color") or "#6F38AA")

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        image_url = settings.get("welcome_image")
        if image_url:
            embed.set_image(url=image_url)

        embed.set_footer(
            text=f"Участник #{member.guild.member_count} • {member.guild.name}",
            icon_url=member.guild.icon.url if member.guild.icon else None
        )

        try:
            await channel.send(content=member.mention, embed=embed)
        except Exception as e:
            logger.error(f"Не удалось отправить приветствие на сервере {member.guild.name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        settings = await get_guild_settings(member.guild.id)
        if not settings.get("leave_enabled"):
            return

        channel_id = settings.get("leave_channel_id")
        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        raw_msg = settings.get("leave_message") or "{username} покинул нас. Нас теперь {count}."
        description = self._format_text(raw_msg, member)

        embed = discord.Embed(
            title="👋 Участник покинул сервер",
            description=description,
            color=0x95A5A6,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Осталось участников: {member.guild.member_count}")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение о выходе: {e}")

    # --- Slash Commands ---
    welcome_group = app_commands.Group(
        name="welcome",
        description="Настройка приветствий новых участников"
    )

    @welcome_group.command(name="setup", description="Настроить канал и сообщение приветствия")
    @app_commands.describe(
        channel="Канал для приветствий",
        title="Заголовок (можно использовать {user}, {username}, {server}, {count})",
        message="Текст приветствия (плейсхолдеры: {user}, {username}, {server}, {count})",
        color="Цвет боковой полосы (HEX, например #6F38AA)",
        image_url="Ссылка на баннер/картинку (опционально)"
    )
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str = "Добро пожаловать!",
        message: str = "Привет новенький, {user}! Добро пожаловать на сервер **{server}**! Ты наш **{count}**-й участник.",
        color: str = "#6F38AA",
        image_url: str = None
    ):
        if not await require_permission(interaction, "settings"):
            return
        await update_guild_settings(
            interaction.guild.id,
            welcome_enabled=1,
            welcome_channel_id=channel.id,
            welcome_title=title,
            welcome_message=message,
            welcome_color=color,
            welcome_image=image_url
        )

        embed = discord.Embed(
            title="✅ Приветствия успешно настроены",
            description=f"Канал приветствий установлен в {channel.mention}.\nСтатус: **Включено**\n\n"
                        f"**Заголовок:** {title}\n"
                        f"**Текст:** {message}\n"
                        f"**Цвет:** `{color}`\n"
                        f"**Картинка:** {image_url or 'Нет'}",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="test", description="Протестировать отправку текущего приветствия")
    async def welcome_test(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        settings = await get_guild_settings(interaction.guild.id)
        channel_id = settings.get("welcome_channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else interaction.channel

        title = self._format_text(settings.get("welcome_title") or "Добро пожаловать!", interaction.user)
        raw_msg = settings.get("welcome_message") or "Привет новенький, {user}! Добро пожаловать на сервер **{server}**!"
        description = self._format_text(raw_msg, interaction.user)
        color = parse_color(settings.get("welcome_color") or "#6F38AA")

        embed = discord.Embed(
            title=f"Тест: {title}",
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        image_url = settings.get("welcome_image")
        if image_url:
            embed.set_image(url=image_url)

        embed.set_footer(
            text=f"Участник #{interaction.guild.member_count} • {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        await interaction.response.send_message("Отправляю тестовое сообщение в канал...", ephemeral=True)
        if isinstance(channel, discord.TextChannel):
            await channel.send(content=f"🔔 Тестовое приветствие для {interaction.user.mention}:", embed=embed)

    @welcome_group.command(name="disable", description="Отключить приветствия")
    async def welcome_disable(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        await update_guild_settings(interaction.guild.id, welcome_enabled=0)
        embed = discord.Embed(
            title="⚙️ Приветствия отключены",
            description="Сообщения с приветствиями больше не будут отправляться.",
            color=COLOR_PRIMARY
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="status", description="Просмотреть настройки приветствий")
    async def welcome_status(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "settings"):
            return
        settings = await get_guild_settings(interaction.guild.id)
        enabled = bool(settings.get("welcome_enabled"))
        ch_id = settings.get("welcome_channel_id")
        channel = interaction.guild.get_channel(ch_id) if ch_id else None

        embed = discord.Embed(
            title="👋 Статус приветствий",
            color=COLOR_PRIMARY
        )
        embed.add_field(name="Состояние", value="🟢 Включено" if enabled else "🔴 Выключено", inline=True)
        embed.add_field(name="Канал", value=channel.mention if channel else "Не установлен", inline=True)
        embed.add_field(name="Цвет", value=f"`{settings.get('welcome_color', '#6F38AA')}`", inline=True)
        embed.add_field(name="Заголовок", value=settings.get("welcome_title") or "Добро пожаловать!", inline=False)
        embed.add_field(name="Текст сообщения", value=settings.get("welcome_message") or "Стандартный", inline=False)
        if settings.get("welcome_image"):
            embed.add_field(name="Баннер", value=settings.get("welcome_image"), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcomer(bot))
