import asyncio
import logging
import sys
import os

# Обеспечение корректного вывода UTF-8 (русский язык) в консоли Windows
if sys.platform.startswith("win"):
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import discord
from discord.ext import commands
from discord import app_commands

from config import TOKEN, GUILD_ID, parse_color, COLOR_PRIMARY, COLOR_ERROR, COLOR_SUCCESS
from database import init_db
from cogs.verification import VerifyButtonView
from cogs.tickets import TicketLaunchView, TicketControlView

# Настройка красивого логирования
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("bot.main")

class UniversalBot(commands.Bot):
    def __init__(self):
        # Включаем все необходимые Privileged Gateway Intents
        intents = discord.Intents.default()
        intents.members = True          # Обязательно для велкамера, авто-роли, модерации
        intents.message_content = True  # Обязательно для транскриптов и чтения сообщений
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        logger.info("Инициализация базы данных SQLite...")
        await init_db()

        # Загрузка расширений (Cogs)
        cogs = [
            "cogs.autorole",
            "cogs.welcomer",
            "cogs.verification",
            "cogs.tickets",
            "cogs.embed_builder",
            "cogs.admin",
            "cogs.panel"
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✓ Модуль '{cog}' успешно загружен.")
            except Exception as e:
                logger.error(f"✗ Ошибка загрузки модуля '{cog}': {e}", exc_info=True)

        # Регистрация постоянных Views (чтобы кнопки работали после перезапуска бота)
        self.add_view(VerifyButtonView())
        self.add_view(TicketLaunchView())
        self.add_view(TicketControlView())

        # Синхронизация Slash-команд
        if GUILD_ID:
            logger.info(f"⚡ Мгновенная регистрация слэш-команд на сервере ID {GUILD_ID}...")
            try:
                guild_obj = discord.Object(id=GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced_guild = await self.tree.sync(guild=guild_obj)
                logger.info(f"✓ Мгновенно синхронизировано {len(synced_guild)} команд на сервере {GUILD_ID} (доступны сразу, без задержек)!")
            except Exception as e:
                logger.error(f"✗ Ошибка мгновенной синхронизации для сервера {GUILD_ID}: {e}")

        # Глобальная синхронизация
        logger.info("Синхронизация глобальных слэш-команд Discord...")
        try:
            synced = await self.tree.sync()
            logger.info(f"✓ Успешно синхронизировано {len(synced)} глобальных слэш-команд!")
        except Exception as e:
            logger.error(f"✗ Ошибка глобальной синхронизации: {e}")

    async def on_ready(self):
        logger.info("=" * 55)
        logger.info(f"  Бот успешно авторизован как: {self.user} (ID: {self.user.id})")
        logger.info(f"  Подключен к серверам: {len(self.guilds)}")
        for g in self.guilds:
            logger.info(f"   • {g.name} (ID: {g.id}) | Участников: {g.member_count}")
        logger.info("=" * 55)

        # Установка статуса присутствия бота
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="/panel | Порядок на сервере"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

bot = UniversalBot()

# Префиксная команда !sync для мгновенной ручной синхронизации слэш-команд
@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_prefix_command(ctx: commands.Context, target_guild_id: str = None):
    """Мгновенно синхронизировать все слэш-команды на текущем сервере или сервере по ID"""
    msg = await ctx.send("⏳ Выполняю мгновенную синхронизацию слэш-команд...")
    try:
        if target_guild_id and target_guild_id.isdigit():
            target_obj = discord.Object(id=int(target_guild_id))
        else:
            target_obj = ctx.guild

        bot.tree.copy_global_to(guild=target_obj)
        synced = await bot.tree.sync(guild=target_obj)
        
        embed = discord.Embed(
            title="⚡ Мгновенная синхронизация завершена",
            description=f"На сервере **{target_obj.id}** успешно зарегистрировано **{len(synced)}** слэш-команд!\n"
                        f"Они сразу же доступны в списке команд при вводе `/`.",
            color=COLOR_SUCCESS
        )
        await msg.edit(content=None, embed=embed)
    except Exception as e:
        await msg.edit(content=f"❌ Ошибка синхронизации: `{e}`")

# Глобальный обработчик ошибок слэш-команд
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        embed = discord.Embed(
            title="🚫 Отказано в доступе",
            description=f"У вас недостаточно прав для использования этой команды.\nТребуются права: `{perms}`",
            color=COLOR_ERROR
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        embed = discord.Embed(
            title="❌ Ошибка прав бота",
            description=f"У бота нет необходимых разрешений на сервере.\nВыдайте боту права: `{perms}`",
            color=COLOR_ERROR
        )
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        logger.error(f"Необработанная ошибка команды: {error}", exc_info=True)
        embed = discord.Embed(
            title="⚠️ Внутренняя ошибка",
            description=f"Произошла ошибка при выполнении команды: `{error}`",
            color=COLOR_ERROR
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass

async def main():
    if not TOKEN or TOKEN == "ВАШ_ТОКЕН_БОТА":
        logger.critical(
            "\n" + "!" * 65 + "\n"
            "ОШИБКА: Токен бота не указан в файле .env!\n"
            "Откройте файл .env и вставьте токен вашего бота:\n"
            "DISCORD_TOKEN=ваш_токен_здесь\n"
            + "!" * 65
        )
        return

    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
