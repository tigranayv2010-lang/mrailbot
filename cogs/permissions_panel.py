import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import add_category_role, remove_category_role, get_all_guild_permissions, clear_category_roles
from permissions import CATEGORIES, require_permission
from config import COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING

logger = logging.getLogger("bot.permissions")

class CategorySelect(discord.ui.Select):
    def __init__(self, selected_category: str = "moderation"):
        options = []
        for cat_key, cat_data in CATEGORIES.items():
            options.append(
                discord.SelectOption(
                    label=cat_data["name"],
                    value=cat_key,
                    description=cat_data["description"][:100],
                    default=(cat_key == selected_category)
                )
            )
        super().__init__(
            placeholder="Выберите категорию команд для настройки...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: PermissionsPanelView = self.view
        view.selected_category = self.values[0]
        # Пересоздаем селект с обновленным default
        view.remove_item(self)
        view.add_item(CategorySelect(selected_category=view.selected_category))
        # Сортируем порядок элементов View
        view.reorder_items()
        await view.refresh(interaction)

class PermissionsRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите роль для добавления/удаления...",
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view: PermissionsPanelView = self.view
        view.selected_role_id = int(self.values[0].id)
        await interaction.response.defer()

class PermissionsPanelView(discord.ui.View):
    """Интерактивная панель настройки прав и ролей доступа к командам бота"""

    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=600)
        self.guild = guild
        self.author_id = author_id
        self.selected_category = "moderation"
        self.selected_role_id = None

        self.add_item(CategorySelect(selected_category=self.selected_category))
        self.add_item(PermissionsRoleSelect())

    def reorder_items(self):
        """Гарантирует правильный порядок элементов на панели"""
        # Сортировка по row
        self.children.sort(key=lambda item: getattr(item, "row", 0) or 0)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Только администратор может настраивать доступы.", ephemeral=True)
            return False
        return True

    async def build_embed(self) -> discord.Embed:
        all_perms = await get_all_guild_permissions(self.guild.id)
        cur_cat = CATEGORIES[self.selected_category]

        embed = discord.Embed(
            title=f"🔐 Панель управления доступами к командам • {self.guild.name}",
            description=(
                "Здесь вы можете гибко назначить роли, которым разрешено использовать определенные команды бота.\n"
                "*Владелец сервера и Администраторы всегда имеют полный доступ.*\n\n"
                f"🎯 **Текущая выбранная категория:** {cur_cat['title']}\n"
                f"📋 **Входящие команды:** {cur_cat['description']}\n"
                "─────────────────────────────────────────"
            ),
            color=COLOR_PRIMARY
        )

        # Вывод статуса по всем категориям
        for cat_key, cat_data in CATEGORIES.items():
            role_ids = all_perms.get(cat_key, [])
            if role_ids:
                roles_str = " ".join([f"<@&{rid}>" for rid in role_ids])
            else:
                roles_str = f"*Стандартно ({cat_data['default_hint']})*"

            prefix = "👉 " if cat_key == self.selected_category else ""
            embed.add_field(
                name=f"{prefix}{cat_data['title']}",
                value=f"Доступ разрешен ролям:\n{roles_str}",
                inline=False
            )

        embed.set_footer(text="1. Выберите категорию -> 2. Выберите роль -> 3. Нажмите кнопку Добавить или Удалить")
        return embed

    async def refresh(self, interaction: discord.Interaction):
        embed = await self.build_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Добавить роль в категорию", style=discord.ButtonStyle.success, emoji="➕", row=2)
    async def btn_add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role_id:
            return await interaction.response.send_message(
                "⚠️ Сначала выберите роль в меню выбора выше!",
                ephemeral=True
            )

        role = self.guild.get_role(self.selected_role_id)
        if not role:
            return await interaction.response.send_message("❌ Роль не найдена на сервере.", ephemeral=True)

        await add_category_role(self.guild.id, self.selected_category, role.id)
        cat_name = CATEGORIES[self.selected_category]["title"]
        await interaction.response.send_message(
            f"✅ Роль {role.mention} успешно получила доступ к категории **{cat_name}**!",
            ephemeral=True
        )
        await self.refresh(interaction)

    @discord.ui.button(label="Удалить роль из категории", style=discord.ButtonStyle.danger, emoji="➖", row=2)
    async def btn_remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role_id:
            return await interaction.response.send_message(
                "⚠️ Сначала выберите роль в меню выбора выше!",
                ephemeral=True
            )

        role = self.guild.get_role(self.selected_role_id)
        role_mention = role.mention if role else f"ID: {self.selected_role_id}"

        removed = await remove_category_role(self.guild.id, self.selected_category, self.selected_role_id)
        cat_name = CATEGORIES[self.selected_category]["title"]
        if removed:
            await interaction.response.send_message(
                f"🗑️ Роль {role_mention} удалена из категории **{cat_name}**.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ Роль {role_mention} не была привязана к этой категории.",
                ephemeral=True
            )
        await self.refresh(interaction)

    @discord.ui.button(label="Сбросить категорию (По умолчанию)", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def btn_reset_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        await clear_category_roles(self.guild.id, self.selected_category)
        cat_name = CATEGORIES[self.selected_category]["title"]
        await interaction.response.send_message(
            f"🔄 Настройки для категории **{cat_name}** сброшены. Действуют стандартные права Discord.",
            ephemeral=True
        )
        await self.refresh(interaction)

class Permissions(commands.Cog):
    """Модуль управления ролями и правами доступа к командам"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="permissions", description="Панель настройки ролей и прав доступа к командам бота")
    async def permissions_command(self, interaction: discord.Interaction):
        # Только владельцы или админы могут настраивать права
        if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                "❌ Только Администратор сервера может настраивать права доступа к командам бота.",
                ephemeral=True
            )

        view = PermissionsPanelView(interaction.guild, interaction.user.id)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Permissions(bot))
