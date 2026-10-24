import io
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import (
    get_guild_settings, update_guild_settings,
    increment_ticket_counter, create_ticket,
    get_ticket_by_channel, get_open_ticket_by_user,
    close_ticket
)
from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING

logger = logging.getLogger("bot.tickets")

class TicketAddUserModal(discord.ui.Modal, title="Добавить участника в тикет"):
    user_id_input = discord.ui.TextInput(
        label="ID пользователя или @упоминание",
        placeholder="Например: 123456789012345678 или @Username",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        val = self.user_id_input.value.strip()
        user_id = None
        if val.startswith("<@") and val.endswith(">"):
            val_clean = val.replace("<@", "").replace("!", "").replace(">", "")
            if val_clean.isdigit():
                user_id = int(val_clean)
        elif val.isdigit():
            user_id = int(val)

        if not user_id:
            return await interaction.response.send_message("❌ Некорректный ID пользователя.", ephemeral=True)

        target_member = interaction.guild.get_member(user_id)
        if not target_member:
            return await interaction.response.send_message("❌ Пользователь не найден на сервере.", ephemeral=True)

        await interaction.channel.set_permissions(
            target_member,
            read_messages=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True
        )

        embed = discord.Embed(
            description=f"👤 Пользователь {target_member.mention} был добавлен в тикет администратором {interaction.user.mention}.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)

class TicketControlView(discord.ui.View):
    """Панель управления внутри открытого канала тикета"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Закрыть тикет",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_close_button"
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Подтверждение закрытия
        confirm_view = discord.ui.View(timeout=30)
        
        async def confirm_callback(btn_interaction: discord.Interaction):
            btn_interaction.response.is_done()
            await Tickets.close_ticket_channel(interaction.channel, btn_interaction.user)

        async def cancel_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.send_message("Отмена закрытия тикета.", ephemeral=True)

        confirm_btn = discord.ui.Button(label="Да, закрыть тикет", style=discord.ButtonStyle.danger, emoji="⚠️")
        confirm_btn.callback = confirm_callback
        confirm_view.add_item(confirm_btn)

        await interaction.response.send_message(
            "Вы уверены, что хотите закрыть этот тикет? Будет сохранен лог переписки, а канал удален.",
            view=confirm_view,
            ephemeral=True
        )

    @discord.ui.button(
        label="Транскрипт",
        style=discord.ButtonStyle.secondary,
        emoji="📄",
        custom_id="ticket_transcript_button"
    )
    async def transcript_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        transcript_file = await Tickets.generate_transcript(interaction.channel)
        await interaction.followup.send(
            content="📄 Транскрипт текущего тикета сформирован:",
            file=transcript_file,
            ephemeral=True
        )

    @discord.ui.button(
        label="Добавить участника",
        style=discord.ButtonStyle.primary,
        emoji="👥",
        custom_id="ticket_adduser_button"
    )
    async def add_user_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketAddUserModal())

    @discord.ui.button(
        label="Позвать поддержку",
        style=discord.ButtonStyle.secondary,
        emoji="🔔",
        custom_id="ticket_alert_button"
    )
    async def alert_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(interaction.guild.id)
        role_id = settings.get("ticket_support_role_id")
        role = interaction.guild.get_role(role_id) if role_id else None

        if role:
            await interaction.response.send_message(
                f"🔔 {role.mention}, внимание! Пользователь {interaction.user.mention} ожидает ответа в тикете."
            )
        else:
            await interaction.response.send_message(
                f"🔔 @here, внимание! Пользователь {interaction.user.mention} ожидает ответа в тикете."
            )

class TicketLaunchView(discord.ui.View):
    """Постоянная кнопка в канале для создания нового тикета"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Создать тикет",
        style=discord.ButtonStyle.primary,
        emoji="📩",
        custom_id="persistent_ticket_create_button"
    )
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        settings = await get_guild_settings(guild.id)

        # Проверка, нет ли уже открытого тикета у пользователя
        existing = await get_open_ticket_by_user(guild.id, user.id)
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                return await interaction.response.send_message(
                    f"⚠️ У вас уже есть активный открытый тикет: {ch.mention}",
                    ephemeral=True
                )

        await interaction.response.defer(ephemeral=True)

        ticket_num = await increment_ticket_counter(guild.id)
        channel_name = f"тикет-{ticket_num:04d}"

        # Настройка прав для канала
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
            user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
                view_channel=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                manage_channels=True,
                manage_permissions=True,
                read_message_history=True,
                view_channel=True
            )
        }

        support_role_id = settings.get("ticket_support_role_id")
        if support_role_id:
            support_role = guild.get_role(support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    view_channel=True
                )

        category_id = settings.get("ticket_category_id")
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Тикет пользователя {user} (ID: {user.id}) | Номер: #{ticket_num:04d}"
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ У бота недостаточно прав для создания текстовых каналов.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Ошибка при создании канала тикета: {e}")
            return await interaction.followup.send("❌ Произошла ошибка при создании тикета.", ephemeral=True)

        # Сохранение тикета в БД
        await create_ticket(guild.id, ticket_channel.id, user.id)

        # Сообщение внутри созданного тикета
        embed = discord.Embed(
            title=f"🎫 Тикет #{ticket_num:04d}",
            description=f"Здравствуйте, {user.mention}!\n"
                        f"Пожалуйста, подробно изложите суть вашего обращения или вопроса.\n"
                        f"Служба поддержки свяжется с вами в ближайшее время.",
            color=COLOR_PRIMARY,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Создатель", value=user.mention, inline=True)
        embed.add_field(name="Номер", value=f"#{ticket_num:04d}", inline=True)
        embed.set_footer(text="Для закрытия или управления тикетом используйте кнопки ниже.")

        view = TicketControlView()
        
        mention_support = f"<@&{support_role_id}> " if support_role_id else ""
        await ticket_channel.send(content=f"{user.mention} {mention_support}", embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Ваш тикет успешно создан: {ticket_channel.mention}",
            ephemeral=True
        )

class Tickets(commands.Cog):
    """Модуль системы тикетов и поддержки"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TicketLaunchView())
        self.bot.add_view(TicketControlView())

    @staticmethod
    async def generate_transcript(channel: discord.TextChannel) -> discord.File:
        """Сформировать текстовый файл транскрипта всех сообщений из канала"""
        buffer = io.StringIO()
        buffer.write(f"=== ТРАНСКРИПТ ТИКЕТА: {channel.name} (ID: {channel.id}) ===\n")
        buffer.write(f"Сервер: {channel.guild.name} (ID: {channel.guild.id})\n")
        buffer.write(f"Создан транскрипт: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")

        messages = [msg async for msg in channel.history(limit=1000, oldest_first=True)]
        for msg in messages:
            time_str = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            author_str = f"{msg.author} ({msg.author.id})"
            content = msg.clean_content or "[Нет текста]"
            buffer.write(f"[{time_str}] {author_str}:\n{content}\n")
            if msg.attachments:
                att_urls = ", ".join([a.url for a in msg.attachments])
                buffer.write(f"  Вложения: {att_urls}\n")
            buffer.write("-" * 40 + "\n")

        buffer.seek(0)
        return discord.File(fp=io.BytesIO(buffer.getvalue().encode("utf-8")), filename=f"transcript-{channel.name}.txt")

    @classmethod
    async def close_ticket_channel(cls, channel: discord.TextChannel, closed_by: discord.Member):
        """Процесс закрытия и архивации тикета"""
        guild = channel.guild
        settings = await get_guild_settings(guild.id)
        ticket_data = await get_ticket_by_channel(channel.id)

        # Завершение в БД
        await close_ticket(channel.id, closed_by.id)

        # Генерация транскрипта
        transcript_file = await cls.generate_transcript(channel)

        # Оповещение в тикете
        embed_closing = discord.Embed(
            title="🔒 Тикет закрывается",
            description=f"Тикет закрыт модератором {closed_by.mention}.\nКанал будет удален через **5 секунд**...",
            color=COLOR_WARNING
        )
        await channel.send(embed=embed_closing)

        # Отправка транскрипта в лог-канал, если настроен
        log_channel_id = settings.get("ticket_log_channel_id")
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if isinstance(log_channel, discord.TextChannel):
                creator_user = guild.get_member(ticket_data["user_id"]) if ticket_data else None
                creator_mention = creator_user.mention if creator_user else f"ID: {ticket_data['user_id'] if ticket_data else 'Неизвестно'}"
                
                log_embed = discord.Embed(
                    title="📁 Лог закрытия тикета",
                    color=COLOR_PRIMARY,
                    timestamp=discord.utils.utcnow()
                )
                log_embed.add_field(name="Канал", value=channel.name, inline=True)
                log_embed.add_field(name="Создатель", value=creator_mention, inline=True)
                log_embed.add_field(name="Закрыл", value=closed_by.mention, inline=True)
                
                try:
                    await log_channel.send(embed=log_embed, file=transcript_file)
                except Exception as e:
                    logger.error(f"Не удалось отправить лог тикета в {log_channel.name}: {e}")

        # Отправка транскрипта создателю в ЛС
        if ticket_data and ticket_data.get("user_id"):
            creator = guild.get_member(ticket_data["user_id"])
            if creator:
                try:
                    dm_embed = discord.Embed(
                        title="🔒 Ваш тикет был закрыт",
                        description=f"Ваш тикет `{channel.name}` на сервере **{guild.name}** был закрыт модератором {closed_by.name}.\n"
                                    f"Копия переписки прикреплена ниже.",
                        color=COLOR_PRIMARY
                    )
                    dm_file = await cls.generate_transcript(channel)
                    await creator.send(embed=dm_embed, file=dm_file)
                except Exception:
                    pass

        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Тикет закрыт модератором {closed_by}")
        except Exception as e:
            logger.error(f"Не удалось удалить канал тикета: {e}")

    # --- Slash Commands ---
    ticket_group = app_commands.Group(
        name="ticket",
        description="Управление системой тикетов",
        default_permissions=discord.Permissions(manage_channels=True)
    )

    @ticket_group.command(name="setup", description="Отправить панель создания тикетов в канал")
    @app_commands.describe(
        channel="Канал для отправки панели тикетов",
        category="Категория, где будут создаваться новые тикеты",
        support_role="Роль поддержки / модераторов, имеющая доступ к тикетам",
        logs_channel="Канал для сохранения транскриптов и логов закрытия",
        title="Заголовок панели",
        description="Текст в панели"
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category: discord.CategoryChannel = None,
        support_role: discord.Role = None,
        logs_channel: discord.TextChannel = None,
        title: str = "Поддержка и создание тикетов",
        description: str = "Если у вас возник вопрос, жалоба или предложение — нажмите кнопку **«Создать тикет»** ниже.\n"
                           "Для вас будет автоматически создан отдельный приватный канал."
    ):
        await update_guild_settings(
            interaction.guild.id,
            ticket_category_id=category.id if category else None,
            ticket_support_role_id=support_role.id if support_role else None,
            ticket_log_channel_id=logs_channel.id if logs_channel else None
        )

        embed = discord.Embed(
            title=title,
            description=description,
            color=COLOR_PRIMARY
        )
        embed.set_footer(
            text=f"Служба поддержки • {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )

        view = TicketLaunchView()
        await channel.send(embed=embed, view=view)

        success = discord.Embed(
            title="✅ Панель тикетов успешно установлена",
            description=f"Панель отправлена в: {channel.mention}\n"
                        f"Категория тикетов: {category.mention if category else 'Не задана'}\n"
                        f"Роль поддержки: {support_role.mention if support_role else 'Не задана'}\n"
                        f"Канал логов: {logs_channel.mention if logs_channel else 'Не задан'}",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=success, ephemeral=True)

    @ticket_group.command(name="close", description="Закрыть текущий канал тикета")
    async def ticket_close(self, interaction: discord.Interaction):
        ticket_data = await get_ticket_by_channel(interaction.channel.id)
        if not ticket_data or ticket_data.get("status") != "open":
            return await interaction.response.send_message("❌ Эта команда может использоваться только внутри открытого тикета.", ephemeral=True)

        await interaction.response.send_message("Инициализирую закрытие тикета...")
        await self.close_ticket_channel(interaction.channel, interaction.user)

    @ticket_group.command(name="add", description="Добавить пользователя в текущий тикет")
    @app_commands.describe(user="Пользователь, которого нужно добавить")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        ticket_data = await get_ticket_by_channel(interaction.channel.id)
        if not ticket_data:
            return await interaction.response.send_message("❌ Эта команда доступна только внутри канала тикета.", ephemeral=True)

        await interaction.channel.set_permissions(
            user,
            read_messages=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            read_message_history=True,
            view_channel=True
        )

        embed = discord.Embed(
            description=f"✅ {user.mention} успешно добавлен в тикет администратором {interaction.user.mention}.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)

    @ticket_group.command(name="remove", description="Удалить пользователя из тикета")
    @app_commands.describe(user="Пользователь, которого нужно удалить")
    async def ticket_remove(self, interaction: discord.Interaction, user: discord.Member):
        ticket_data = await get_ticket_by_channel(interaction.channel.id)
        if not ticket_data:
            return await interaction.response.send_message("❌ Эта команда доступна только внутри канала тикета.", ephemeral=True)

        if user.id == ticket_data.get("user_id"):
            return await interaction.response.send_message("❌ Нельзя удалить создателя тикета из его собственного тикета.", ephemeral=True)

        await interaction.channel.set_permissions(user, overwrite=None)
        embed = discord.Embed(
            description=f"🚫 {user.mention} был удален из тикета.",
            color=COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
