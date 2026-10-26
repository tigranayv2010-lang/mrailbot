import time
import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import get_guild_settings, update_guild_settings, parse_id_list, format_id_list
from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO
from cogs.verification import VerifyButtonView
from cogs.tickets import TicketLaunchView, TicketBuilderView
from cogs.embed_builder import EmbedBuilderView
from cogs.permissions_panel import PermissionsPanelView
from permissions import require_permission

logger = logging.getLogger("bot.panel")

class WelcomeEditModal(discord.ui.Modal, title="Настройка текста Велкамера"):
    title_input = discord.ui.TextInput(
        label="Заголовок приветствия",
        placeholder="Добро пожаловать!",
        default="Добро пожаловать!",
        required=True
    )
    message_input = discord.ui.TextInput(
        label="Текст приветствия ({user}, {server}, {count})",
        style=discord.TextStyle.paragraph,
        placeholder="Привет новенький, {user}! Добро пожаловать на сервер {server}!",
        required=True,
        max_length=1500
    )
    color_input = discord.ui.TextInput(
        label="Цвет боковой полосы (HEX)",
        placeholder="#6F38AA",
        default="#6F38AA",
        required=False
    )

    def __init__(self, panel_view, current_title: str, current_msg: str, current_color: str):
        super().__init__()
        self.panel_view = panel_view
        self.title_input.default = current_title or "Добро пожаловать!"
        self.message_input.default = current_msg or "Привет новенький, {user}! Добро пожаловать на сервер {server}!"
        self.color_input.default = current_color or "#6F38AA"

    async def on_submit(self, interaction: discord.Interaction):
        await update_guild_settings(
            interaction.guild.id,
            welcome_title=self.title_input.value.strip(),
            welcome_message=self.message_input.value.strip(),
            welcome_color=self.color_input.value.strip() or "#6F38AA"
        )
        await interaction.response.send_message("✅ Текст приветствия успешно обновлен!", ephemeral=True)
        await self.panel_view.refresh_view(interaction)

class BotControlPanelView(discord.ui.View):
    """Интерактивная панель управления ботом в Discord"""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, author_id: int):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.author_id = author_id
        self.current_tab = "main"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Панелью может управлять только администратор, вызвавший её.", ephemeral=True)
            return False
        return True

    async def build_main_embed(self) -> discord.Embed:
        settings = await get_guild_settings(self.guild.id)

        # Статусы модулей с поддержкой мульти-ролей
        ar_ids = parse_id_list(settings.get("autorole_ids")) or parse_id_list(settings.get("autorole_id"))
        ar_roles = [self.guild.get_role(rid) for rid in ar_ids if self.guild.get_role(rid)]
        ar_str = " ".join([r.mention for r in ar_roles]) if ar_roles else "Роли не выбраны"
        autorole_status = f"🟢 Вкл ({ar_str})" if settings.get("autorole_enabled") else "🔴 Выкл"

        welcome_ch = self.guild.get_channel(settings.get("welcome_channel_id")) if settings.get("welcome_channel_id") else None
        welcome_status = f"🟢 Вкл ({welcome_ch.mention if welcome_ch else 'Канал не найден'})" if settings.get("welcome_enabled") else "🔴 Выкл"

        vr_ids = parse_id_list(settings.get("verify_role_ids")) or parse_id_list(settings.get("verify_role_id"))
        vr_roles = [self.guild.get_role(rid) for rid in vr_ids if self.guild.get_role(rid)]
        vr_str = " ".join([r.mention for r in vr_roles]) if vr_roles else "Роли не выбраны"
        verify_status = f"🟢 Настроена ({vr_str})" if settings.get("verify_enabled") else "🔴 Выкл"

        tr_ids = parse_id_list(settings.get("ticket_support_role_ids")) or parse_id_list(settings.get("ticket_support_role_id"))
        tr_roles = [self.guild.get_role(rid) for rid in tr_ids if self.guild.get_role(rid)]
        tr_str = " ".join([r.mention for r in tr_roles]) if tr_roles else "Все админы"
        ticket_cat = self.guild.get_channel(settings.get("ticket_category_id")) if settings.get("ticket_category_id") else None
        ticket_status = f"🟢 Категория: {ticket_cat.name if ticket_cat else 'По умолчанию'} | Роли: {tr_str}"

        embed = discord.Embed(
            title=f"🎛️ Панель управления ботом • {self.guild.name}",
            description="Добро пожаловать в центр управления сервером! Выберите нужный раздел ниже для быстрой настройки бота.",
            color=COLOR_PRIMARY,
            timestamp=discord.utils.utcnow()
        )
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        embed.add_field(name="👥 Участников", value=str(self.guild.member_count), inline=True)
        embed.add_field(name="💬 Каналов", value=str(len(self.guild.channels)), inline=True)
        embed.add_field(name="🏓 Пинг бота", value=f"{round(self.bot.latency * 1000)} мс", inline=True)

        embed.add_field(name="────────── Состояние систем ──────────", value="", inline=False)
        embed.add_field(name="👤 Авто-роль новичкам", value=autorole_status, inline=True)
        embed.add_field(name="👋 Велкамер (Приветствия)", value=welcome_status, inline=True)
        embed.add_field(name="🛡️ Верификация", value=verify_status, inline=True)
        embed.add_field(name="🎫 Система тикетов", value=ticket_status, inline=False)

        embed.set_footer(text="Универсальный Бот • Для переключения нажимайте кнопки ниже")
        return embed

    async def refresh_view(self, interaction: discord.Interaction):
        embed = await self.build_main_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

    # --- Кнопки навигации ---
    @discord.ui.button(label="Главная", style=discord.ButtonStyle.primary, emoji="🏠", row=0)
    async def btn_home(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_tab = "main"
        await self.refresh_view(interaction)

    @discord.ui.button(label="Авто-роль", style=discord.ButtonStyle.secondary, emoji="👤", row=0)
    async def btn_autorole(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        ar_ids = parse_id_list(settings.get("autorole_ids")) or parse_id_list(settings.get("autorole_id"))
        current_roles = [self.guild.get_role(rid) for rid in ar_ids if self.guild.get_role(rid)]
        roles_str = ", ".join([r.mention for r in current_roles]) if current_roles else "Не установлены"
        enabled = bool(settings.get("autorole_enabled"))

        embed = discord.Embed(
            title="👤 Управление Авто-ролью (Мульти-выбор)",
            description="Автоматическая выдача ролей участникам при первом входе на сервер.\n\n"
                        f"**Текущий статус:** {'🟢 Включено' if enabled else '🔴 Выключено'}\n"
                        f"**Назначенные роли:** {roles_str}\n\n"
                        "💡 *Выберите одну или несколько ролей в меню ниже (до 25).* ",
            color=COLOR_PRIMARY
        )

        sub_view = discord.ui.View(timeout=300)

        # Multi-role select
        role_select = discord.ui.RoleSelect(
            placeholder="Выберите одну или несколько ролей (до 25)...",
            min_values=1,
            max_values=25
        )

        async def on_role_select(sel_interaction: discord.Interaction):
            chosen_role_ids = [int(r.id) for r in role_select.values]
            await update_guild_settings(
                sel_interaction.guild.id,
                autorole_enabled=1,
                autorole_ids=format_id_list(chosen_role_ids),
                autorole_id=chosen_role_ids[0] if chosen_role_ids else None
            )
            roles_mentions = ", ".join([f"<@&{rid}>" for rid in chosen_role_ids])
            await sel_interaction.response.send_message(f"✅ Авто-роли обновлены: {roles_mentions} (Включено)!", ephemeral=True)
            await self.refresh_view(interaction)

        role_select.callback = on_role_select
        sub_view.add_item(role_select)

        # Toggle button
        toggle_btn = discord.ui.Button(
            label="Выключить" if enabled else "Включить",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            emoji="🔄"
        )
        async def on_toggle(btn_interaction: discord.Interaction):
            new_state = 0 if enabled else 1
            await update_guild_settings(btn_interaction.guild.id, autorole_enabled=new_state)
            await btn_interaction.response.send_message(f"✅ Авто-роль {'включена' if new_state else 'отключена'}!", ephemeral=True)
            await self.refresh_view(interaction)

        toggle_btn.callback = on_toggle
        sub_view.add_item(toggle_btn)

        await interaction.response.send_message(embed=embed, view=sub_view, ephemeral=True)

    @discord.ui.button(label="Велкамер", style=discord.ButtonStyle.secondary, emoji="👋", row=0)
    async def btn_welcomer(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        enabled = bool(settings.get("welcome_enabled"))
        current_ch = self.guild.get_channel(settings.get("welcome_channel_id")) if settings.get("welcome_channel_id") else None

        embed = discord.Embed(
            title="👋 Настройка Приветствий (Велкамер)",
            description=f"**Статус:** {'🟢 Включено' if enabled else '🔴 Выключено'}\n"
                        f"**Канал приветствий:** {current_ch.mention if current_ch else 'Не выбран'}\n"
                        f"**Заголовок:** {settings.get('welcome_title')}\n"
                        f"**Текст:** {settings.get('welcome_message')}\n\n"
                        "💡 *Выберите канал ниже или нажмите «Изменить текст», чтобы персонализировать сообщение.*",
            color=COLOR_PRIMARY
        )

        sub_view = discord.ui.View(timeout=300)

        ch_select = discord.ui.ChannelSelect(
            placeholder="Выберите канал для приветствий...",
            channel_types=[discord.ChannelType.text]
        )
        async def on_ch_select(sel_interaction: discord.Interaction):
            ch_id = int(sel_interaction.data["values"][0])
            await update_guild_settings(sel_interaction.guild.id, welcome_enabled=1, welcome_channel_id=ch_id)
            await sel_interaction.response.send_message(f"✅ Канал приветствий установлен в <#{ch_id}>!", ephemeral=True)
            await self.refresh_view(interaction)
        ch_select.callback = on_ch_select
        sub_view.add_item(ch_select)

        # Edit text button
        edit_btn = discord.ui.Button(label="Изменить текст и цвет", style=discord.ButtonStyle.primary, emoji="✏️")
        async def on_edit(btn_interaction: discord.Interaction):
            modal = WelcomeEditModal(
                self,
                settings.get("welcome_title", "Добро пожаловать!"),
                settings.get("welcome_message", ""),
                settings.get("welcome_color", "#FFFFFF")
            )
            await btn_interaction.response.send_modal(modal)
        edit_btn.callback = on_edit
        sub_view.add_item(edit_btn)

        # Toggle button
        toggle_btn = discord.ui.Button(
            label="Выключить" if enabled else "Включить",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            emoji="🔄"
        )
        async def on_welcome_toggle(btn_interaction: discord.Interaction):
            new_state = 0 if enabled else 1
            await update_guild_settings(btn_interaction.guild.id, welcome_enabled=new_state)
            await btn_interaction.response.send_message(f"✅ Приветствия {'включены' if new_state else 'отключены'}!", ephemeral=True)
            await self.refresh_view(interaction)
        toggle_btn.callback = on_welcome_toggle
        sub_view.add_item(toggle_btn)

        await interaction.response.send_message(embed=embed, view=sub_view, ephemeral=True)

    @discord.ui.button(label="Верификация", style=discord.ButtonStyle.secondary, emoji="🛡️", row=1)
    async def btn_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        vr_ids = parse_id_list(settings.get("verify_role_ids")) or parse_id_list(settings.get("verify_role_id"))
        current_roles = [self.guild.get_role(rid) for rid in vr_ids if self.guild.get_role(rid)]
        roles_str = ", ".join([r.mention for r in current_roles]) if current_roles else "Не настроены"

        embed = discord.Embed(
            title="🛡️ Управление Верификацией (Мульти-выбор)",
            description=f"**Роли за верификацию:** {roles_str}\n\n"
                        "💡 *Выберите одну или несколько ролей, которые будут выдаваться при нажатии на кнопку верификации, "
                        "а затем отправьте сообщение с кнопкой в нужный канал.*",
            color=COLOR_PRIMARY
        )

        sub_view = discord.ui.View(timeout=300)

        # Multi-role select
        role_select = discord.ui.RoleSelect(
            placeholder="Выберите роли за верификацию (до 25)...",
            min_values=1,
            max_values=25
        )
        async def on_vrole_select(sel_interaction: discord.Interaction):
            chosen_role_ids = [int(r.id) for r in role_select.values]
            await update_guild_settings(
                sel_interaction.guild.id,
                verify_enabled=1,
                verify_role_ids=format_id_list(chosen_role_ids),
                verify_role_id=chosen_role_ids[0] if chosen_role_ids else None
            )
            roles_mentions = ", ".join([f"<@&{rid}>" for rid in chosen_role_ids])
            await sel_interaction.response.send_message(f"✅ Роли верификации установлены: {roles_mentions}", ephemeral=True)
            await self.refresh_view(interaction)
        role_select.callback = on_vrole_select
        sub_view.add_item(role_select)

        # Send panel button
        send_btn = discord.ui.Button(label="Отправить кнопку в канал...", style=discord.ButtonStyle.success, emoji="📨")
        async def on_send_panel(btn_interaction: discord.Interaction):
            ch_sub = discord.ui.View(timeout=120)
            ch_select = discord.ui.ChannelSelect(placeholder="Выберите канал для кнопки верификации...", channel_types=[discord.ChannelType.text])
            async def ch_callback(ch_interaction: discord.Interaction):
                target_channel = ch_interaction.guild.get_channel(int(ch_interaction.data["values"][0]))
                v_embed = discord.Embed(
                    title="Верификация на сервере",
                    description="Нажмите на кнопку **«Пройти верификацию»** ниже, чтобы получить доступ ко всем каналам сервера!",
                    color=COLOR_PRIMARY
                )
                v_embed.set_footer(text=f"Защита сервера • {ch_interaction.guild.name}")
                await target_channel.send(embed=v_embed, view=VerifyButtonView())
                await ch_interaction.response.send_message(f"✅ Панель верификации отправлена в {target_channel.mention}!", ephemeral=True)
            ch_select.callback = ch_callback
            ch_sub.add_item(ch_select)
            await btn_interaction.response.send_message("Выберите канал, куда опубликовать панель:", view=ch_sub, ephemeral=True)
        send_btn.callback = on_send_panel
        sub_view.add_item(send_btn)

        await interaction.response.send_message(embed=embed, view=sub_view, ephemeral=True)

    @discord.ui.button(label="Тикеты", style=discord.ButtonStyle.secondary, emoji="🎫", row=1)
    async def btn_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = await get_guild_settings(self.guild.id)
        cat = self.guild.get_channel(settings.get("ticket_category_id")) if settings.get("ticket_category_id") else None
        
        tr_ids = parse_id_list(settings.get("ticket_support_role_ids")) or parse_id_list(settings.get("ticket_support_role_id"))
        s_roles = [self.guild.get_role(rid) for rid in tr_ids if self.guild.get_role(rid)]
        roles_str = ", ".join([r.mention for r in s_roles]) if s_roles else "Не выбраны (все админы)"

        log_ch = self.guild.get_channel(settings.get("ticket_log_channel_id")) if settings.get("ticket_log_channel_id") else None

        embed = discord.Embed(
            title="🎫 Управление Системой Тикетов",
            description=f"**Категория тикетов:** {cat.name if cat else 'Не выбрана'}\n"
                        f"**Роли поддержки (мульти):** {roles_str}\n"
                        f"**Канал логов/транскриптов:** {log_ch.mention if log_ch else 'Не выбран'}\n\n"
                        "💡 *Вы можете настроить тикеты с нуля (кнопки, тексты, оформление) через Конструктор!*",
            color=COLOR_PRIMARY
        )

        sub_view = discord.ui.View(timeout=300)

        # Builder button (Конструктор с нуля)
        builder_btn = discord.ui.Button(label="🛠️ Конструктор тикетов с нуля", style=discord.ButtonStyle.primary, emoji="🛠️")
        async def on_builder_click(btn_interaction: discord.Interaction):
            t_builder = TicketBuilderView(self.guild, btn_interaction.user.id)
            embed_b = await t_builder.build_embed()
            await btn_interaction.response.send_message(embed=embed_b, view=t_builder, ephemeral=True)
        builder_btn.callback = on_builder_click
        sub_view.add_item(builder_btn)

        # Support roles multi-select
        role_select = discord.ui.RoleSelect(
            placeholder="Выберите роли службы поддержки (до 25)...",
            min_values=1,
            max_values=25
        )
        async def on_srole_select(sel_interaction: discord.Interaction):
            chosen_role_ids = [int(r.id) for r in role_select.values]
            await update_guild_settings(
                sel_interaction.guild.id,
                ticket_support_role_ids=format_id_list(chosen_role_ids),
                ticket_support_role_id=chosen_role_ids[0] if chosen_role_ids else None
            )
            roles_mentions = ", ".join([f"<@&{rid}>" for rid in chosen_role_ids])
            await sel_interaction.response.send_message(f"✅ Роли поддержки тикетов обновлены: {roles_mentions}", ephemeral=True)
            await self.refresh_view(interaction)
        role_select.callback = on_srole_select
        sub_view.add_item(role_select)

        # Send ticket launch view button
        publish_btn = discord.ui.Button(label="Опубликовать панель тикетов в канал", style=discord.ButtonStyle.success, emoji="📩")
        async def on_pub_click(btn_interaction: discord.Interaction):
            ch_sub = discord.ui.View(timeout=120)
            ch_select = discord.ui.ChannelSelect(placeholder="Выберите канал для кнопки создания тикетов...", channel_types=[discord.ChannelType.text])
            async def ch_ticket_cb(ch_interaction: discord.Interaction):
                target_channel = ch_interaction.guild.get_channel(int(ch_interaction.data["values"][0]))
                t_embed = discord.Embed(
                    title=settings.get("ticket_panel_title", "Поддержка и создание тикетов"),
                    description=settings.get("ticket_panel_desc", "Если у вас возник вопрос, жалоба или предложение — нажмите кнопку ниже.\nДля вас будет автоматически создан приватный канал."),
                    color=COLOR_PRIMARY
                )
                t_embed.set_footer(text=f"Служба поддержки • {ch_interaction.guild.name}")
                await target_channel.send(
                    embed=t_embed,
                    view=TicketLaunchView(
                        label=settings.get("ticket_btn_label", "Создать тикет"),
                        emoji=settings.get("ticket_btn_emoji", "📩")
                    )
                )
                await ch_interaction.response.send_message(f"✅ Панель тикетов отправлена в {target_channel.mention}!", ephemeral=True)
            ch_select.callback = ch_ticket_cb
            ch_sub.add_item(ch_select)
            await btn_interaction.response.send_message("Выберите канал для размещения кнопки тикетов:", view=ch_sub, ephemeral=True)
        publish_btn.callback = on_pub_click
        sub_view.add_item(publish_btn)

        await interaction.response.send_message(embed=embed, view=sub_view, ephemeral=True)

    @discord.ui.button(label="Конструктор Embed", style=discord.ButtonStyle.success, emoji="🎨", row=1)
    async def btn_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        builder_view = EmbedBuilderView(author_id=interaction.user.id)
        embeds = builder_view.build_embeds()
        await interaction.response.send_message(
            content="🎨 **Интерактивный конструктор Embed-сообщений** (Предпросмотр ниже):\n"
                    "Вы можете настроить заголовок, текст, цвета или нажать кнопку **«Шаблон как на скриншоте»**!",
            embeds=embeds,
            view=builder_view,
            ephemeral=True
        )

    @discord.ui.button(label="Доступы к командам", style=discord.ButtonStyle.primary, emoji="🔐", row=2)
    async def btn_permissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        perm_view = PermissionsPanelView(self.guild, interaction.user.id)
        embed = await perm_view.build_embed()
        await interaction.response.send_message(embed=embed, view=perm_view, ephemeral=True)

class Panel(commands.Cog):
    """Главная интерактивная Панель Управления ботом"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="panel", description="Открыть главную интерактивную панель управления сервером и ботом")
    async def panel_command(self, interaction: discord.Interaction):
        if not await require_permission(interaction, "panel"):
            return
        panel_view = BotControlPanelView(self.bot, interaction.guild, interaction.user.id)
        embed = await panel_view.build_main_embed()
        await interaction.response.send_message(embed=embed, view=panel_view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Panel(bot))
