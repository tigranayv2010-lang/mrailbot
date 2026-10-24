import re
import datetime
import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import add_warn, get_warns, remove_warn, clear_warns
from config import COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_PRIMARY

logger = logging.getLogger("bot.admin")

def parse_duration(duration_str: str) -> datetime.timedelta | None:
    """Парсинг строки длительности, например '10m', '2h', '1d'"""
    match = re.match(r"^(\d+)\s*([smhdw])$", duration_str.strip().lower())
    if not match:
        return None
    val, unit = match.groups()
    val = int(val)
    units = {
        's': datetime.timedelta(seconds=val),
        'm': datetime.timedelta(minutes=val),
        'h': datetime.timedelta(hours=val),
        'd': datetime.timedelta(days=val),
        'w': datetime.timedelta(weeks=val),
    }
    return units.get(unit)

class Admin(commands.Cog):
    """Модуль команд администрирования и модерации"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- KICK ---
    @app_commands.command(name="kick", description="Выгнать участника с сервера")
    @app_commands.describe(member="Участник", reason="Причина исключения")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Причина не указана"):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Вы не можете выгнать участника с равной или более высокой ролью.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ У бота недостаточно прав для исключения этого участника.", ephemeral=True)

        try:
            # Уведомление в ЛС перед киком
            try:
                dm_embed = discord.Embed(
                    title=f"⚠️ Вы были исключены с сервера {interaction.guild.name}",
                    description=f"**Причина:** {reason}\n**Модератор:** {interaction.user}",
                    color=COLOR_ERROR
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

            await member.kick(reason=f"{reason} (Модератор: {interaction.user})")
            embed = discord.Embed(
                title="👢 Участник исключен",
                description=f"**Пользователь:** {member.mention} (`{member.id}`)\n"
                            f"**Модератор:** {interaction.user.mention}\n"
                            f"**Причина:** {reason}",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось исключить: {e}", ephemeral=True)

    # --- BAN ---
    @app_commands.command(name="ban", description="Заблокировать участника на сервере")
    @app_commands.describe(
        member="Участник",
        reason="Причина блокировки",
        delete_messages_days="Удалить сообщения за последние N дней (0-7)"
    )
    @app_commands.default_permissions(ban_members=True)
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "Причина не указана",
        delete_messages_days: app_commands.Range[int, 0, 7] = 0
    ):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Вы не можете забанить участника с равной или более высокой ролью.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ У бота недостаточно прав для блокировки этого участника.", ephemeral=True)

        try:
            try:
                dm_embed = discord.Embed(
                    title=f"⛔ Вы были заблокированы на сервере {interaction.guild.name}",
                    description=f"**Причина:** {reason}\n**Модератор:** {interaction.user}",
                    color=COLOR_ERROR
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

            seconds = delete_messages_days * 86400
            await member.ban(reason=f"{reason} (Модератор: {interaction.user})", delete_message_seconds=seconds)
            embed = discord.Embed(
                title="⛔ Участник заблокирован",
                description=f"**Пользователь:** {member.mention} (`{member.id}`)\n"
                            f"**Модератор:** {interaction.user.mention}\n"
                            f"**Причина:** {reason}\n"
                            f"**Удаление сообщений:** за {delete_messages_days} дн.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось забанить: {e}", ephemeral=True)

    # --- UNBAN ---
    @app_commands.command(name="unban", description="Разблокировать пользователя по его ID")
    @app_commands.describe(user_id="ID заблокированного пользователя", reason="Причина разблокировки")
    @app_commands.default_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Причина не указана"):
        if not user_id.isdigit():
            return await interaction.response.send_message("❌ Введите корректный числовой ID пользователя.", ephemeral=True)

        user_obj = discord.Object(id=int(user_id))
        try:
            await interaction.guild.unban(user_obj, reason=f"{reason} (Модератор: {interaction.user})")
            embed = discord.Embed(
                title="🔓 Пользователь разблокирован",
                description=f"**ID пользователя:** `{user_id}`\n"
                            f"**Модератор:** {interaction.user.mention}\n"
                            f"**Причина:** {reason}",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed)
        except discord.NotFound:
            await interaction.response.send_message("❌ Пользователь с таким ID не найден в списке забаненных.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    # --- TIMEOUT / MUTE ---
    @app_commands.command(name="mute", description="Заглушить участника (таймаут)")
    @app_commands.describe(
        member="Участник",
        duration="Длительность (например: 10m, 1h, 1d, максимум 28d)",
        reason="Причина"
    )
    @app_commands.default_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str = "10m",
        reason: str = "Нарушение правил"
    ):
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Вы не можете заглушить участника с равной или более высокой ролью.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ У бота недостаточно прав для таймаута этого участника.", ephemeral=True)

        delta = parse_duration(duration)
        if not delta:
            return await interaction.response.send_message(
                "❌ Неверный формат времени. Примеры: `10m` (минуты), `2h` (часы), `1d` (дни).",
                ephemeral=True
            )

        if delta > datetime.timedelta(days=28):
            return await interaction.response.send_message("❌ Максимальное время таймаута в Discord — 28 дней.", ephemeral=True)

        try:
            until = discord.utils.utcnow() + delta
            await member.timeout(until, reason=f"{reason} (Модератор: {interaction.user})")
            embed = discord.Embed(
                title="🔇 Участник заглушен (Таймаут)",
                description=f"**Пользователь:** {member.mention}\n"
                            f"**Длительность:** `{duration}`\n"
                            f"**До:** <t:{int(until.timestamp())}:f> (<t:{int(until.timestamp())}:R>)\n"
                            f"**Модератор:** {interaction.user.mention}\n"
                            f"**Причина:** {reason}",
                color=COLOR_WARNING
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось заглушить: {e}", ephemeral=True)

    # --- UNMUTE ---
    @app_commands.command(name="unmute", description="Снять таймаут/заглушение с участника")
    @app_commands.describe(member="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        try:
            await member.timeout(None, reason=f"Снятие таймаута (Модератор: {interaction.user})")
            embed = discord.Embed(
                title="🔊 Заглушение снято",
                description=f"С участника {member.mention} было снято ограничение общения модератором {interaction.user.mention}.",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось снять ограничение: {e}", ephemeral=True)

    # --- CLEAR / PURGE ---
    @app_commands.command(name="clear", description="Очистить сообщения в текущем канале")
    @app_commands.describe(
        count="Количество сообщений для удаления (1-100)",
        user="Удалить только сообщения этого пользователя (опционально)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 1, 100],
        user: discord.Member = None
    ):
        await interaction.response.defer(ephemeral=True)

        def check(m):
            return user is None or m.author.id == user.id

        try:
            deleted = await interaction.channel.purge(limit=count, check=check)
            msg = f"🧹 Удалено сообщений: **{len(deleted)}**"
            if user:
                msg += f" от пользователя {user.mention}"
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Не удалось удалить сообщения: {e}", ephemeral=True)

    # --- WARN ---
    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(member="Участник", reason="Причина предупреждения")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        warn_id = await add_warn(interaction.guild.id, member.id, interaction.user.id, reason)
        all_warns = await get_warns(interaction.guild.id, member.id)

        try:
            dm_embed = discord.Embed(
                title=f"⚠️ Вам выдано предупреждение на сервере {interaction.guild.name}",
                description=f"**Причина:** {reason}\n**Всего предупреждений:** {len(all_warns)}",
                color=COLOR_WARNING
            )
            await member.send(embed=dm_embed)
        except Exception:
            pass

        embed = discord.Embed(
            title="⚠️ Предупреждение выдано",
            description=f"**Участник:** {member.mention}\n"
                        f"**ID предупреждения:** `#{warn_id}`\n"
                        f"**Причина:** {reason}\n"
                        f"**Всего предупреждений:** {len(all_warns)}\n"
                        f"**Модератор:** {interaction.user.mention}",
            color=COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed)

    # --- WARNS LIST ---
    @app_commands.command(name="warns", description="Посмотреть список предупреждений участника")
    @app_commands.describe(member="Участник")
    @app_commands.default_permissions(moderate_members=True)
    async def warns(self, interaction: discord.Interaction, member: discord.Member):
        warn_list = await get_warns(interaction.guild.id, member.id)

        embed = discord.Embed(
            title=f"📋 Предупреждения: {member.name}",
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if not warn_list:
            embed.description = "У пользователя нет активных предупреждений."
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        for w in warn_list[:10]:
            mod = interaction.guild.get_member(w["moderator_id"])
            mod_str = mod.mention if mod else f"ID: {w['moderator_id']}"
            embed.add_field(
                name=f"Варн #{w['warn_id']} • {w['created_at'][:19]}",
                value=f"**Причина:** {w['reason']}\n**Выдал:** {mod_str}",
                inline=False
            )

        if len(warn_list) > 10:
            embed.set_footer(text=f"Показано 10 из {len(warn_list)} предупреждений")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- UNWARN ---
    @app_commands.command(name="unwarn", description="Снять конкретное предупреждение по его ID")
    @app_commands.describe(warn_id="ID предупреждения")
    @app_commands.default_permissions(moderate_members=True)
    async def unwarn(self, interaction: discord.Interaction, warn_id: int):
        success = await remove_warn(warn_id, interaction.guild.id)
        if success:
            await interaction.response.send_message(f"✅ Предупреждение `#{warn_id}` успешно удалено.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Предупреждение `#{warn_id}` не найдено на этом сервере.", ephemeral=True)

    # --- SLOWMODE ---
    @app_commands.command(name="slowmode", description="Установить медленный режим (slowmode) в канале")
    @app_commands.describe(seconds="Задержка между сообщениями в секундах (0 - отключить)")
    @app_commands.default_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        try:
            await interaction.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await interaction.response.send_message("⚡ Медленный режим отключен.")
            else:
                await interaction.response.send_message(f"⏳ Установлен медленный режим: **{seconds} сек.**")
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось изменить slowmode: {e}", ephemeral=True)

    # --- LOCK / UNLOCK ---
    @app_commands.command(name="lock", description="Заблокировать канал для отправки сообщений участниками")
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
            embed = discord.Embed(
                title="🔒 Канал заблокирован",
                description="Отправка сообщений в этот канал временно ограничена администрацией.",
                color=COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка блокировки: {e}", ephemeral=True)

    @app_commands.command(name="unlock", description="Разблокировать канал для отправки сообщений")
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None)
            embed = discord.Embed(
                title="🔓 Канал разблокирован",
                description="Отправка сообщений в канал снова открыта.",
                color=COLOR_SUCCESS
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка разблокировки: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
