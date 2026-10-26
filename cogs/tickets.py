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
    close_ticket, parse_id_list, format_id_list
)
from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING
from permissions import require_permission

logger = logging.getLogger("bot.tickets")

# --- Модальное окно добавления участника ---

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
            read_message_history=True,
            view_channel=True
        )

        embed = discord.Embed(
            description=f"👤 Пользователь {target_member.mention} был добавлен в тикет администратором {interaction.user.mention}.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)

# --- Панель управления внутри открытого тикета ---

class TicketControlView(discord.ui.View):
    """Панель управления внутри созданного тикета с настраиваемыми кнопками"""
    def __init__(
        self,
        close_label: str = "Закрыть тикет",
        transcript_label: str = "Транскрипт",
        adduser_label: str = "Добавить участника",
        alert_label: str = "Позвать поддержку"
    ):
        super().__init__(timeout=None)
        self.clear_items()

        # Кнопка закрытия
        btn_close = discord.ui.Button(
            label=close_label or "Закрыть тикет",
            style=discord.ButtonStyle.danger,
            emoji="🔒",
            custom_id="ticket_close_button"
        )
        btn_close.callback = self.close_button_callback
        self.add_item(btn_close)

        # Кнопка транскрипта
        btn_trans = discord.ui.Button(
            label=transcript_label or "Транскрипт",
            style=discord.ButtonStyle.secondary,
            emoji="📄",
            custom_id="ticket_transcript_button"
        )
        btn_trans.callback = self.transcript_button_callback
        self.add_item(btn_trans)

        # Кнопка добавления участника
        btn_adduser = discord.ui.Button(
            label=adduser_label or "Добавить участника",
            style=discord.ButtonStyle.primary,
            emoji="👥",
            custom_id="ticket_adduser_button"
        )
        btn_adduser.callback = self.adduser_button_callback
        self.add_item(btn_adduser)

        # Кнопка вызова поддержки
        btn_alert = discord.ui.Button(
            label=alert_label or "Позвать поддержку",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id="ticket_alert_button"
        )
        btn_alert.callback = self.alert_button_callback
        self.add_item(btn_alert)

    async def close_button_callback(self, interaction: discord.Interaction):
        confirm_view = discord.ui.View(timeout=30)

        async def confirm_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.defer()
            await Tickets.close_ticket_channel(interaction.channel, btn_interaction.user)

        async def cancel_callback(btn_interaction: discord.Interaction):
            await btn_interaction.response.send_message("Отмена закрытия тикета.", ephemeral=True)

        confirm_btn = discord.ui.Button(label="Да, закрыть тикет", style=discord.ButtonStyle.danger, emoji="⚠️")
        confirm_btn.callback = confirm_callback
        confirm_view.add_item(confirm_btn)

        await interaction.response.send_message(
            "Вы уверены, что хотите закрыть этот тикет? Будет сформирован транскрипт, а канал удален.",
            view=confirm_view,
            ephemeral=True
        )

    async def transcript_button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        transcript_file = await Tickets.generate_transcript(interaction.channel)
        await interaction.followup.send(
            content="📄 Транскрипт текущего тикета сформирован:",
            file=transcript_file,
            ephemeral=True
        )

    async def adduser_button_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketAddUserModal())

    async def alert_button_callback(self, interaction: discord.Interaction):
        settings = await get_guild_settings(interaction.guild.id)
        role_ids = parse_id_list(settings.get("ticket_support_role_ids")) or parse_id_list(settings.get("ticket_support_role_id"))

        mentions = []
        for rid in role_ids:
            r = interaction.guild.get_role(rid)
            if r:
                mentions.append(r.mention)

        if mentions:
            await interaction.response.send_message(
                f"🔔 {', '.join(mentions)}, внимание! Пользователь {interaction.user.mention} ожидает ответа в тикете."
            )
        else:
            await interaction.response.send_message(
                f"🔔 @here, внимание! Пользователь {interaction.user.mention} ожидает ответа в тикете."
            )

# --- Постоянная кнопка создания тикета в канале ---

class TicketLaunchView(discord.ui.View):
    """Постоянная кнопка в канале для создания нового тикета"""
    def __init__(self, label: str = "Создать тикет", emoji: str = "📩"):
        super().__init__(timeout=None)
        self.clear_items()
        btn = discord.ui.Button(
            label=label or "Создать тикет",
            style=discord.ButtonStyle.primary,
            emoji=emoji or "📩",
            custom_id="persistent_ticket_create_button"
        )
        btn.callback = self.create_ticket_callback
        self.add_item(btn)

    async def create_ticket_callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user

        settings = await get_guild_settings(guild.id)

        # Проверка, нет ли уже открытого тикета
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

        # Мульти-роли поддержки
        support_role_ids = parse_id_list(settings.get("ticket_support_role_ids")) or parse_id_list(settings.get("ticket_support_role_id"))
        mention_parts = []
        for rid in support_role_ids:
            support_role = guild.get_role(rid)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    view_channel=True
                )
                mention_parts.append(support_role.mention)

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

        # Настраиваемый текст внутри тикета
        raw_title = settings.get("ticket_inside_title") or "Тикет #{number}"
        raw_desc = settings.get("ticket_inside_desc") or "Здравствуйте, {user}!\nОпишите ваш вопрос или проблему. Служба поддержки свяжется с вами в ближайшее время."

        formatted_title = raw_title.replace("{number}", f"{ticket_num:04d}").replace("{user}", user.display_name)
        formatted_desc = (
            raw_desc.replace("{number}", f"{ticket_num:04d}")
            .replace("{user}", user.mention)
            .replace("{username}", user.name)
            .replace("{server}", guild.name)
        )

        embed = discord.Embed(
            title=formatted_title,
            description=formatted_desc,
            color=parse_color(settings.get("ticket_panel_color", "#FFFFFF")),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Создатель", value=user.mention, inline=True)
        embed.add_field(name="Номер", value=f"#{ticket_num:04d}", inline=True)
        embed.set_footer(text="Для управления тикетом используйте кнопки ниже.")

        # Создаем View внутри тикета с кастомными названиями кнопок
        view = TicketControlView(
            close_label=settings.get("ticket_close_btn_label", "Закрыть тикет"),
            transcript_label=settings.get("ticket_transcript_btn_label", "Транскрипт"),
            adduser_label=settings.get("ticket_adduser_btn_label", "Добавить участника"),
            alert_label=settings.get("ticket_alert_btn_label", "Позвать поддержку")
        )

        mention_str = " ".join(mention_parts)
        await ticket_channel.send(content=f"{user.mention} {mention_str}".strip(), embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Ваш тикет успешно создан: {ticket_channel.mention}",
            ephemeral=True
        )

# --- Модальные окна конструктора тикетов с нуля ---

class TicketPanelEditModal(discord.ui.Modal, title="Настройка внешней панели тикетов"):
    title_input = discord.ui.TextInput(
        label="Заголовок панели",
        placeholder="Поддержка и создание тикетов",
        default="Поддержка и создание тикетов",
        required=True,
        max_length=256
    )
    desc_input = discord.ui.TextInput(
        label="Текст описания панели",
        style=discord.TextStyle.paragraph,
        placeholder="Если у вас возник вопрос или жалоба — нажмите кнопку ниже...",
        required=True,
        max_length=1500
    )
    btn_label_input = discord.ui.TextInput(
        label="Текст на кнопке создания",
        placeholder="Создать тикет (или Открыть тикет / Подать жалобу)",
        default="Создать тикет",
        required=True,
        max_length=80
    )
    btn_emoji_input = discord.ui.TextInput(
        label="Эмодзи на кнопке",
        placeholder="📩, 🎫, 💼, ❓",
        default="📩",
        required=False,
        max_length=20
    )
    color_input = discord.ui.TextInput(
        label="Цвет боковой линии (HEX)",
        placeholder="#FFFFFF (по умолчанию белый)",
        default="#FFFFFF",
        required=False,
        max_length=10
    )

    def __init__(self, builder_view, settings: dict):
        super().__init__()
        self.builder_view = builder_view
        self.title_input.default = settings.get("ticket_panel_title", "Поддержка и создание тикетов")
        self.desc_input.default = settings.get("ticket_panel_desc", "Если у вас возник вопрос, жалоба или предложение — нажмите кнопку ниже.")
        self.btn_label_input.default = settings.get("ticket_btn_label", "Создать тикет")
        self.btn_emoji_input.default = settings.get("ticket_btn_emoji", "📩")
        self.color_input.default = settings.get("ticket_panel_color", "#FFFFFF")

    async def on_submit(self, interaction: discord.Interaction):
        await update_guild_settings(
            interaction.guild.id,
            ticket_panel_title=self.title_input.value.strip(),
            ticket_panel_desc=self.desc_input.value.strip(),
            ticket_btn_label=self.btn_label_input.value.strip() or "Создать тикет",
            ticket_btn_emoji=self.btn_emoji_input.value.strip() or "📩",
            ticket_panel_color=self.color_input.value.strip() or "#FFFFFF"
        )
        await interaction.response.send_message("✅ Внешний вид панели тикетов успешно обновлен!", ephemeral=True)
        await self.builder_view.refresh(interaction)

class TicketInsideEditModal(discord.ui.Modal, title="Настройка текста внутри тикета"):
    inside_title_input = discord.ui.TextInput(
        label="Заголовок внутри тикета ({number}, {user})",
        placeholder="Тикет #{number}",
        default="Тикет #{number}",
        required=True,
        max_length=256
    )
    inside_desc_input = discord.ui.TextInput(
        label="Сообщение внутри ({user}, {number}, {server})",
        style=discord.TextStyle.paragraph,
        placeholder="Здравствуйте, {user}!\nОпишите ваш вопрос или проблему...",
        required=True,
        max_length=1500
    )
    close_btn_input = discord.ui.TextInput(
        label="Название кнопки Закрыть",
        placeholder="Закрыть тикет",
        default="Закрыть тикет",
        required=True,
        max_length=80
    )
    transcript_btn_input = discord.ui.TextInput(
        label="Название кнопки Транскрипт",
        placeholder="Транскрипт",
        default="Транскрипт",
        required=True,
        max_length=80
    )
    alert_btn_input = discord.ui.TextInput(
        label="Название кнопки Вызов поддержки",
        placeholder="Позвать поддержку",
        default="Позвать поддержку",
        required=True,
        max_length=80
    )

    def __init__(self, builder_view, settings: dict):
        super().__init__()
        self.builder_view = builder_view
        self.inside_title_input.default = settings.get("ticket_inside_title", "Тикет #{number}")
        self.inside_desc_input.default = settings.get("ticket_inside_desc", "Здравствуйте, {user}!\nОпишите ваш вопрос или проблему. Служба поддержки свяжется с вами в ближайшее время.")
        self.close_btn_input.default = settings.get("ticket_close_btn_label", "Закрыть тикет")
        self.transcript_btn_input.default = settings.get("ticket_transcript_btn_label", "Транскрипт")
        self.alert_btn_input.default = settings.get("ticket_alert_btn_label", "Позвать поддержку")

    async def on_submit(self, interaction: discord.Interaction):
        await update_guild_settings(
            interaction.guild.id,
            ticket_inside_title=self.inside_title_input.value.strip(),
            ticket_inside_desc=self.inside_desc_input.value.strip(),
            ticket_close_btn_label=self.close_btn_input.value.strip() or "Закрыть тикет",
            ticket_transcript_btn_label=self.transcript_btn_input.value.strip() or "Транскрипт",
            ticket_alert_btn_label=self.alert_btn_input.value.strip() or "Позвать поддержку"
        )
        await interaction.response.send_message("✅ Настройки текста внутри тикета успешно сохранены!", ephemeral=True)
        await self.builder_view.refresh(interaction)

# --- Интерактивный конструктор создания тикетов с нуля ---

class TicketBuilderView(discord.ui.View):
    """Интерактивный конструктор всей системы тикетов в Discord"""

    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=600)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Только администратор может управлять этим конструктором.", ephemeral=True)
            return False
        return True

    async def build_embed(self) -> discord.Embed:
        settings = await get_guild_settings(self.guild.id)

        role_ids = parse_id_list(settings.get("ticket_support_role_ids")) or parse_id_list(settings.get("ticket_support_role_id"))
        roles_str = " ".join([f"<@&{rid}>" for rid in role_ids]) if role_ids else "*Не назначены (все админы)*"

        cat = self.guild.get_channel(settings.get("ticket_category_id")) if settings.get("ticket_category_id") else None
        cat_str = cat.name if cat else "*По умолчанию*"

        log_ch = self.guild.get_channel(settings.get("ticket_log_channel_id")) if settings.get("ticket_log_channel_id") else None
        log_str = log_ch.mention if log_ch else "*Не назначен*"

        embed = discord.Embed(
            title=f"🛠️ Конструктор тикет-системы с нуля • {self.guild.name}",
            description=(
                "Здесь вы можете с нуля полностью настроить тексты, кнопки и внешний вид системы тикетов.\n\n"
                "**1. Внешняя панель (в канале):**\n"
                f"• Заголовок: **{settings.get('ticket_panel_title', 'Поддержка и создание тикетов')}**\n"
                f"• Текст: {settings.get('ticket_panel_desc', 'Стандартный')}\n"
                f"• Кнопка: `{settings.get('ticket_btn_emoji', '📩')} {settings.get('ticket_btn_label', 'Создать тикет')}`\n"
                f"• Цвет боковой линии: `{settings.get('ticket_panel_color', '#FFFFFF')}`\n\n"
                "**2. Внутри созданного тикета:**\n"
                f"• Заголовок: `{settings.get('ticket_inside_title', 'Тикет #{number}')}`\n"
                f"• Кнопки: `{settings.get('ticket_close_btn_label', 'Закрыть тикет')}`, `{settings.get('ticket_transcript_btn_label', 'Транскрипт')}`, `{settings.get('ticket_alert_btn_label', 'Позвать поддержку')}`\n\n"
                "**3. Технические параметры:**\n"
                f"• Роли поддержки (мульти): {roles_str}\n"
                f"• Категория тикетов: {cat_str}\n"
                f"• Канал сохранения логов: {log_str}"
            ),
            color=parse_color(settings.get("ticket_panel_color", "#FFFFFF"))
        )
        embed.set_footer(text="Используйте кнопки ниже для редактирования и публикации панели в канал")
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = await self.build_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Текст внешней панели", style=discord.ButtonStyle.primary, emoji="📝", row=0)
    async def btn_edit_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        await interaction.response.send_modal(TicketPanelEditModal(self, settings))

    @discord.ui.button(label="Текст внутри тикета", style=discord.ButtonStyle.primary, emoji="💬", row=0)
    async def btn_edit_inside(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        await interaction.response.send_modal(TicketInsideEditModal(self, settings))

    @discord.ui.button(label="Роли поддержки (Мульти)", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def btn_support_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub_view = discord.ui.View(timeout=180)
        role_select = discord.ui.RoleSelect(
            placeholder="Выберите одну или несколько ролей поддержки (до 25)...",
            min_values=1,
            max_values=25
        )

        async def role_cb(sel_interaction: discord.Interaction):
            chosen_rids = [int(r.id) for r in role_select.values]
            await update_guild_settings(
                sel_interaction.guild.id,
                ticket_support_role_ids=format_id_list(chosen_rids),
                ticket_support_role_id=chosen_rids[0] if chosen_rids else None
            )
            roles_mentions = ", ".join([f"<@&{rid}>" for rid in chosen_rids])
            await sel_interaction.response.send_message(
                f"✅ Роли поддержки тикетов обновлены: {roles_mentions}",
                ephemeral=True
            )
            await self.refresh(interaction)

        role_select.callback = role_cb
        sub_view.add_item(role_select)
        await interaction.response.send_message("Выберите роли, которые должны иметь доступ ко всем тикетам:", view=sub_view, ephemeral=True)

    @discord.ui.button(label="Категория тикетов", style=discord.ButtonStyle.secondary, emoji="📁", row=1)
    async def btn_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub_view = discord.ui.View(timeout=180)
        cat_select = discord.ui.ChannelSelect(
            placeholder="Выберите категорию для создания каналов...",
            channel_types=[discord.ChannelType.category]
        )

        async def cat_cb(sel_interaction: discord.Interaction):
            cat_id = int(cat_select.values[0].id)
            await update_guild_settings(sel_interaction.guild.id, ticket_category_id=cat_id)
            await sel_interaction.response.send_message(f"✅ Категория для тикетов установлена в **{cat_select.values[0].name}**!", ephemeral=True)
            await self.refresh(interaction)

        cat_select.callback = cat_cb
        sub_view.add_item(cat_select)
        await interaction.response.send_message("Выберите категорию Discord:", view=sub_view, ephemeral=True)

    @discord.ui.button(label="Канал логов", style=discord.ButtonStyle.secondary, emoji="📜", row=1)
    async def btn_log_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub_view = discord.ui.View(timeout=180)
        ch_select = discord.ui.ChannelSelect(
            placeholder="Выберите канал для логов и транскриптов...",
            channel_types=[discord.ChannelType.text]
        )

        async def ch_cb(sel_interaction: discord.Interaction):
            ch_id = int(ch_select.values[0].id)
            await update_guild_settings(sel_interaction.guild.id, ticket_log_channel_id=ch_id)
            await sel_interaction.response.send_message(f"✅ Канал логов тикетов установлен в <#{ch_id}>!", ephemeral=True)
            await self.refresh(interaction)

        ch_select.callback = ch_cb
        sub_view.add_item(ch_select)
        await interaction.response.send_message("Выберите текстовый канал для логов:", view=sub_view, ephemeral=True)

    @discord.ui.button(label="Опубликовать тикет-панель в канал", style=discord.ButtonStyle.success, emoji="🚀", row=2)
    async def btn_publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        sub_view = discord.ui.View(timeout=180)
        ch_select = discord.ui.ChannelSelect(
            placeholder="Выберите канал для отправки готовой панели тикетов...",
            channel_types=[discord.ChannelType.text]
        )

        async def pub_cb(sel_interaction: discord.Interaction):
            target_channel = sel_interaction.guild.get_channel(int(ch_select.values[0].id))
            if not isinstance(target_channel, discord.TextChannel):
                return await sel_interaction.response.send_message("❌ Некорректный текстовый канал.", ephemeral=True)

            settings = await get_guild_settings(sel_interaction.guild.id)

            panel_embed = discord.Embed(
                title=settings.get("ticket_panel_title", "Поддержка и создание тикетов"),
                description=settings.get("ticket_panel_desc", "Если у вас возник вопрос, жалоба или предложение — нажмите кнопку ниже.\nДля вас будет автоматически создан отдельный приватный канал."),
                color=parse_color(settings.get("ticket_panel_color", "#FFFFFF"))
            )
            panel_embed.set_footer(
                text=f"Служба поддержки • {sel_interaction.guild.name}",
                icon_url=sel_interaction.guild.icon.url if sel_interaction.guild.icon else None
            )

            launch_view = TicketLaunchView(
                label=settings.get("ticket_btn_label", "Создать тикет"),
                emoji=settings.get("ticket_btn_emoji", "📩")
            )

            try:
                await target_channel.send(embed=panel_embed, view=launch_view)
                await sel_interaction.response.send_message(f"✅ Панель тикетов успешно опубликована в канале {target_channel.mention}!", ephemeral=True)
            except discord.Forbidden:
                await sel_interaction.response.send_message("❌ У бота нет прав для отправки сообщений в этот канал.", ephemeral=True)

        ch_select.callback = pub_cb
        sub_view.add_item(ch_select)
        await interaction.response.send_message("Куда отправить панель с кнопкой?", view=sub_view, ephemeral=True)

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
    @app_commands.command(name="ticket_builder", description="Конструктор создания тикет-системы с нуля (тексты, кнопки, роли)")
    async def direct_ticket_builder(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "tickets"):
            return
        view = TicketBuilderView(interaction.guild, interaction.user.id)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    ticket_group = app_commands.Group(
        name="ticket",
        description="Управление системой тикетов"
    )

    @ticket_group.command(name="builder", description="Конструктор создания тикет-системы с нуля (тексты, кнопки, роли)")
    async def ticket_builder(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "tickets"):
            return
        view = TicketBuilderView(interaction.guild, interaction.user.id)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ticket_group.command(name="setup", description="Быстро отправить панель создания тикетов в канал")
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
        if not await require_permission(interaction, "tickets"):
            return

        await update_guild_settings(
            interaction.guild.id,
            ticket_category_id=category.id if category else None,
            ticket_support_role_id=support_role.id if support_role else None,
            ticket_support_role_ids=str(support_role.id) if support_role else "",
            ticket_log_channel_id=logs_channel.id if logs_channel else None,
            ticket_panel_title=title,
            ticket_panel_desc=description
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
        if not await require_permission(interaction, "tickets"):
            return
        ticket_data = await get_ticket_by_channel(interaction.channel.id)
        if not ticket_data or ticket_data.get("status") != "open":
            return await interaction.response.send_message("❌ Эта команда может использоваться только внутри открытого тикета.", ephemeral=True)

        await interaction.response.send_message("Инициализирую закрытие тикета...")
        await self.close_ticket_channel(interaction.channel, interaction.user)

    @ticket_group.command(name="add", description="Добавить пользователя в текущий тикет")
    @app_commands.describe(user="Пользователь, которого нужно добавить")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        if not await require_permission(interaction, "tickets"):
            return
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
        if not await require_permission(interaction, "tickets"):
            return
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
