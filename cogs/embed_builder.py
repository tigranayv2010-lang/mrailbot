import json
import logging
import discord
from discord import app_commands
from discord.ext import commands

from config import parse_color, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR

logger = logging.getLogger("bot.embed_builder")

# --- Modals for Interactive Builder ---

class EditMainModal(discord.ui.Modal, title="Редактирование Заголовка и Описания"):
    title_input = discord.ui.TextInput(
        label="Заголовок Embed",
        placeholder="Например: Информация о проекте",
        required=False,
        max_length=256
    )
    description_input = discord.ui.TextInput(
        label="Описание (поддерживает Markdown, эмодзи)",
        style=discord.TextStyle.paragraph,
        placeholder="Введите текст сообщения...",
        required=True,
        max_length=4000
    )

    def __init__(self, current_title: str = "", current_desc: str = ""):
        super().__init__()
        self.title_input.default = current_title
        self.description_input.default = current_desc

    async def on_submit(self, interaction: discord.Interaction):
        view: EmbedBuilderView = self.builder_view
        view.current_data["title"] = self.title_input.value.strip()
        view.current_data["description"] = self.description_input.value
        await view.update_preview(interaction)

class EditStyleModal(discord.ui.Modal, title="Настройка Цвета и Медиа"):
    color_input = discord.ui.TextInput(
        label="Цвет боковой полосы (HEX)",
        placeholder="#6F38AA (фиолетовый как на скриншоте)",
        default="#6F38AA",
        required=False,
        max_length=10
    )
    thumbnail_input = discord.ui.TextInput(
        label="URL миниатюры (Thumbnail справа вверху)",
        placeholder="https://example.com/logo.png",
        required=False
    )
    image_input = discord.ui.TextInput(
        label="URL большого изображения/баннера",
        placeholder="https://example.com/banner.png",
        required=False
    )

    def __init__(self, current_color: str, current_thumb: str, current_img: str):
        super().__init__()
        self.color_input.default = current_color or "#6F38AA"
        self.thumbnail_input.default = current_thumb or ""
        self.image_input.default = current_img or ""

    async def on_submit(self, interaction: discord.Interaction):
        view: EmbedBuilderView = self.builder_view
        view.current_data["color"] = self.color_input.value.strip() or "#6F38AA"
        view.current_data["thumbnail"] = self.thumbnail_input.value.strip() or None
        view.current_data["image"] = self.image_input.value.strip() or None
        await view.update_preview(interaction)

class EditFooterAuthorModal(discord.ui.Modal, title="Настройка Автора и Подвала"):
    author_input = discord.ui.TextInput(
        label="Имя автора (сверху над заголовком)",
        placeholder="Например: Nevskiy RP",
        required=False,
        max_length=100
    )
    author_icon_input = discord.ui.TextInput(
        label="URL иконки автора",
        placeholder="https://example.com/icon.png",
        required=False
    )
    footer_input = discord.ui.TextInput(
        label="Текст подвала (Footer)",
        placeholder="Сервер • 2026",
        required=False,
        max_length=200
    )
    footer_icon_input = discord.ui.TextInput(
        label="URL иконки подвала",
        placeholder="https://example.com/footer.png",
        required=False
    )

    def __init__(self, author: str, author_icon: str, footer: str, footer_icon: str):
        super().__init__()
        self.author_input.default = author or ""
        self.author_icon_input.default = author_icon or ""
        self.footer_input.default = footer or ""
        self.footer_icon_input.default = footer_icon or ""

    async def on_submit(self, interaction: discord.Interaction):
        view: EmbedBuilderView = self.builder_view
        view.current_data["author"] = self.author_input.value.strip() or None
        view.current_data["author_icon"] = self.author_icon_input.value.strip() or None
        view.current_data["footer"] = self.footer_input.value.strip() or None
        view.current_data["footer_icon"] = self.footer_icon_input.value.strip() or None
        await view.update_preview(interaction)

class AddFieldModal(discord.ui.Modal, title="Добавить поле (Field) в Embed"):
    field_name = discord.ui.TextInput(
        label="Название поля",
        placeholder="Например: Правила проекта",
        required=True,
        max_length=256
    )
    field_value = discord.ui.TextInput(
        label="Содержимое поля",
        style=discord.TextStyle.paragraph,
        placeholder="Текст внутри поля...",
        required=True,
        max_length=1024
    )
    inline_input = discord.ui.TextInput(
        label="В одну строку? (1 - да, 0 - нет)",
        placeholder="0",
        default="0",
        required=False,
        max_length=1
    )

    async def on_submit(self, interaction: discord.Interaction):
        view: EmbedBuilderView = self.builder_view
        is_inline = self.inline_input.value.strip() == "1"
        view.current_data["fields"].append({
            "name": self.field_name.value.strip(),
            "value": self.field_value.value.strip(),
            "inline": is_inline
        })
        await view.update_preview(interaction)

# --- Select for Channel Destination ---

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите канал для отправки готового сообщения...",
            channel_types=[discord.ChannelType.text]
        )

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        view: EmbedBuilderView = self.view
        embeds = view.build_embeds()

        if not embeds:
            return await interaction.response.send_message("❌ Нельзя отправить пустой Embed. Заполните хотя бы описание или заголовок.", ephemeral=True)

        try:
            target_channel = interaction.guild.get_channel(channel.id)
            if not isinstance(target_channel, discord.TextChannel):
                return await interaction.response.send_message("❌ Некорректный текстовый канал.", ephemeral=True)

            await target_channel.send(embeds=embeds)
            await interaction.response.send_message(f"✅ Сообщение успешно отправлено в {target_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота нет прав на отправку сообщений в этот канал.", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка при отправке Embed: {e}")
            await interaction.response.send_message(f"❌ Ошибка отправки: {e}", ephemeral=True)

# --- Main Interactive Builder View ---

class EmbedBuilderView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=600)
        self.author_id = author_id
        
        # Данные первого эмбеда
        self.current_data = {
            "title": "Информация о проекте",
            "description": "Привет новенький!\nТы попал на наш сервер.\n\nЗдесь вы можете настроить любой текст, цвета и ссылки на каналы!",
            "color": "#6F38AA",
            "thumbnail": None,
            "image": None,
            "author": None,
            "author_icon": None,
            "footer": None,
            "footer_icon": None,
            "fields": []
        }
        # Опциональный второй эмбед (как на скриншоте пользователя!)
        self.second_embed_data = None

        self.add_item(ChannelSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Только автор команды может управлять этим конструктором.", ephemeral=True)
            return False
        return True

    def build_single_embed(self, data: dict) -> discord.Embed:
        color = parse_color(data.get("color") or "#6F38AA")
        embed = discord.Embed(
            title=data.get("title") or None,
            description=data.get("description") or None,
            color=color
        )
        if data.get("author"):
            embed.set_author(name=data["author"], icon_url=data.get("author_icon") or None)
        if data.get("footer"):
            embed.set_footer(text=data["footer"], icon_url=data.get("footer_icon") or None)
        if data.get("thumbnail"):
            embed.set_thumbnail(url=data["thumbnail"])
        if data.get("image"):
            embed.set_image(url=data["image"])
        for f in data.get("fields", []):
            embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        return embed

    def build_embeds(self) -> list[discord.Embed]:
        embeds = []
        if self.current_data.get("title") or self.current_data.get("description") or self.current_data.get("fields"):
            embeds.append(self.build_single_embed(self.current_data))
        if self.second_embed_data and (self.second_embed_data.get("title") or self.second_embed_data.get("description")):
            embeds.append(self.build_single_embed(self.second_embed_data))
        return embeds

    async def update_preview(self, interaction: discord.Interaction):
        embeds = self.build_embeds()
        if not embeds:
            temp = discord.Embed(title="Предпросмотр", description="[Embed пока пуст. Заполните текст через кнопки ниже]", color=COLOR_PRIMARY)
            embeds = [temp]
        await interaction.response.edit_message(content="🎨 **Интерактивный конструктор Embed-сообщений** (Предпросмотр ниже):", embeds=embeds, view=self)

    @discord.ui.button(label="Текст & Заголовок", style=discord.ButtonStyle.primary, emoji="📝", row=1)
    async def btn_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditMainModal(self.current_data.get("title", ""), self.current_data.get("description", ""))
        modal.builder_view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Цвет & Картинки", style=discord.ButtonStyle.secondary, emoji="🎨", row=1)
    async def btn_style(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditStyleModal(self.current_data.get("color", "#6F38AA"), self.current_data.get("thumbnail", ""), self.current_data.get("image", ""))
        modal.builder_view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Автор & Подвал", style=discord.ButtonStyle.secondary, emoji="👤", row=1)
    async def btn_author_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EditFooterAuthorModal(
            self.current_data.get("author", ""),
            self.current_data.get("author_icon", ""),
            self.current_data.get("footer", ""),
            self.current_data.get("footer_icon", "")
        )
        modal.builder_view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="+ Поле (Field)", style=discord.ButtonStyle.secondary, emoji="➕", row=1)
    async def btn_add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.current_data.get("fields", [])) >= 25:
            return await interaction.response.send_message("❌ Достигнут лимит в 25 полей.", ephemeral=True)
        modal = AddFieldModal()
        modal.builder_view = self
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Очистить поля", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def btn_clear_fields(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_data["fields"] = []
        await self.update_preview(interaction)

    @discord.ui.button(label="Шаблон как на скриншоте", style=discord.ButtonStyle.success, emoji="📋", row=2)
    async def btn_screenshot_template(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Загружаем точно такой шаблон, как на фото пользователя
        self.current_data = {
            "title": "Информация о проекте",
            "description": (
                "Привет новенький!\n"
                "Ты попал на сервер \"Невский\"\n"
                "Тут ты можешь стать от Помощника Машиниста До Начальника депо! Или даже выше!\n\n"
                "Что есть на нашем проекте ?\n"
                "У нас есть поезда сервер про железную дорогу: ,\n"
                "большая карта,\n"
                "дружный коллектив."
            ),
            "color": "#6F38AA",
            "thumbnail": None,
            "image": None,
            "author": None,
            "author_icon": None,
            "footer": None,
            "footer_icon": None,
            "fields": []
        }
        self.second_embed_data = {
            "title": "Каналы и/их назначения",
            "description": (
                "**Информация по каналам:**\n"
                "**Проект**\n"
                "• Правила Discord - # • 🍁 правила-discord - правила дискорд сервера.\n"
                "• Новости - • 📢 ☂️ новости - новостной канал.\n"
                "• Правила Minecraft - # • 🍁 правила-discord - правила майнкрафт сервера.\n"
                "• Тест на проходку - # • 👩 верификация\n\n"
                "**RolePlay**\n"
                "• Расписание - # неизвестно - расписание поездов\n"
                "• Банкомат - # • 🍁 банкомат - банкомат.\n"
                "• сборка сервера - • 🫐 сборка-сервака\n"
                "• Общие приказы - # • 💐 кадровый-аудит-рук-состава - Выписываются приказы не косаемо железной дороги.\n\n"
                "**Discord - channel**\n"
                "• Выговоры - # 🪓 гр-аудит-взысканий - выдаются выговоры/предупреждения если (3/3) выговоров/предупреждений сотрудник снимается с должности.\n"
                "• команды ботов - # 🪚 🤖 команды-ботов - Команды ботам.\n\n"
                "**Валюта - channel**\n"
                "• поддержка сервера - # (поддержка-сервера) - Поддержать сервер реальной валютой."
            ),
            "color": "#6F38AA",
            "thumbnail": None,
            "image": None,
            "author": None,
            "author_icon": None,
            "footer": None,
            "footer_icon": None,
            "fields": []
        }
        await self.update_preview(interaction)

    @discord.ui.button(label="Удалить 2-й Embed", style=discord.ButtonStyle.secondary, emoji="❌", row=2)
    async def btn_remove_second(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.second_embed_data = None
        await self.update_preview(interaction)

class EmbedBuilder(commands.Cog):
    """Модуль создания красивых Embed-сообщений (как на скриншоте)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    embed_group = app_commands.Group(
        name="embed",
        description="Конструктор красивых Embed-сообщений",
        default_permissions=discord.Permissions(manage_messages=True)
    )

    @embed_group.command(name="builder", description="Открыть интерактивный визуальный конструктор сообщений")
    async def embed_builder(self, interaction: discord.Interaction):
        view = EmbedBuilderView(author_id=interaction.user.id)
        embeds = view.build_embeds()
        await interaction.response.send_message(
            content="🎨 **Интерактивный конструктор Embed-сообщений** (Предпросмотр ниже):\n"
                    "Используйте кнопки для настройки текста, цвета, добавления полей и шаблона со скриншота, "
                    "а затем выберите канал в выпадающем списке.",
            embeds=embeds,
            view=view,
            ephemeral=True
        )

    @embed_group.command(name="screenshot_preset", description="Отправить точную копию оформления со скриншота в канал")
    @app_commands.describe(channel="Канал, куда отправить оформление")
    async def embed_screenshot_preset(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed1 = discord.Embed(
            title="Информация о проекте",
            description=(
                "Привет новенький!\n"
                "Ты попал на сервер \"Невский\"\n"
                "Тут ты можешь стать от Помощника Машиниста До Начальника депо! Или даже выше!\n\n"
                "Что есть на нашем проекте ?\n"
                "У нас есть поезда сервер про железную дорогу: ,\n"
                "большая карта,\n"
                "дружный коллектив."
            ),
            color=parse_color("#6F38AA")
        )

        embed2 = discord.Embed(
            title="Каналы и/их назначения",
            description=(
                "**Информация по каналам:**\n"
                "**Проект**\n"
                "• Правила Discord - # • 🍁 правила-discord - правила дискорд сервера.\n"
                "• Новости - • 📢 ☂️ новости - новостной канал.\n"
                "• Правила Minecraft - # • 🍁 правила-discord - правила майнкрафт сервера.\n"
                "• Тест на проходку - # • 👩 верификация\n\n"
                "**RolePlay**\n"
                "• Расписание - # неизвестно - расписание поездов\n"
                "• Банкомат - # • 🍁 банкомат - банкомат.\n"
                "• сборка сервера - • 🫐 сборка-сервака\n"
                "• Общие приказы - # • 💐 кадровый-аудит-рук-состава - Выписываются приказы не косаемо железной дороги.\n\n"
                "**Discord - channel**\n"
                "• Выговоры - # 🪓 гр-аудит-взысканий - выдаются выговоры/предупреждения если (3/3) выговоров/предупреждений сотрудник снимается с должности.\n"
                "• команды ботов - # 🪚 🤖 команды-ботов - Команды ботам.\n\n"
                "**Валюта - channel**\n"
                "• поддержка сервера - # (поддержка-сервера) - Поддержать сервер реальной валютой."
            ),
            color=parse_color("#6F38AA")
        )

        try:
            await channel.send(embeds=[embed1, embed2])
            await interaction.response.send_message(f"✅ Сообщение со скриншота успешно отправлено в {channel.mention}!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Не удалось отправить сообщение: {e}", ephemeral=True)

    @embed_group.command(name="send", description="Быстро отправить кастомный Embed в канал")
    @app_commands.describe(
        channel="Канал для отправки",
        title="Заголовок",
        description="Текст описания",
        color="HEX-код цвета (например, #6F38AA)",
        image="Ссылка на большое изображение",
        thumbnail="Ссылка на миниатюру",
        footer="Текст подвала"
    )
    async def embed_send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        description: str,
        title: str = None,
        color: str = "#6F38AA",
        image: str = None,
        thumbnail: str = None,
        footer: str = None
    ):
        embed = discord.Embed(
            title=title,
            description=description,
            color=parse_color(color)
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if image:
            embed.set_image(url=image)
        if footer:
            embed.set_footer(text=footer)

        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(f"✅ Сообщение отправлено в {channel.mention}!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка отправки: {e}", ephemeral=True)

    @embed_group.command(name="json_send", description="Отправить Embed по сырому JSON (Discohook format)")
    @app_commands.describe(
        channel="Канал для отправки",
        json_data="JSON структура embed или списка embeds"
    )
    async def embed_json_send(self, interaction: discord.Interaction, channel: discord.TextChannel, json_data: str):
        try:
            parsed = json.loads(json_data)
            embeds = []
            if isinstance(parsed, dict):
                if "embeds" in parsed:
                    for em_data in parsed["embeds"]:
                        embeds.append(discord.Embed.from_dict(em_data))
                else:
                    embeds.append(discord.Embed.from_dict(parsed))
            elif isinstance(parsed, list):
                for em_data in parsed:
                    embeds.append(discord.Embed.from_dict(em_data))

            if not embeds:
                return await interaction.response.send_message("❌ Не найдено валидных данных Embed в JSON.", ephemeral=True)

            await channel.send(embeds=embeds)
            await interaction.response.send_message(f"✅ JSON Embed успешно отправлен в {channel.mention}!", ephemeral=True)
        except json.JSONDecodeError:
            await interaction.response.send_message("❌ Невалидный JSON формат.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка отправки: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))
