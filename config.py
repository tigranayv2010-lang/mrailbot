import os
import discord
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")

# ID сервера для мгновенной регистрации слэш-команд (без ожидания глобального кэша Discord)
raw_guild_id = os.getenv("GUILD_ID", "1479400508312784938")
try:
    GUILD_ID = int(raw_guild_id) if raw_guild_id else 1479400508312784938
except ValueError:
    GUILD_ID = 1479400508312784938

# Основная палитра цветов (по умолчанию белый цвет для всех Embed сообщений)
COLOR_PRIMARY = 0xFFFFFF  # Чистый белый цвет
COLOR_WHITE = 0xFFFFFF    # Белый
COLOR_SUCCESS = 0x2ECC71  # Зеленый
COLOR_ERROR = 0xE74C3C    # Красный
COLOR_WARNING = 0xF1C40F  # Желтый
COLOR_INFO = 0xFFFFFF     # Белый
COLOR_PURPLE = 0x6F38AA   # Фиолетовый (опциональный)

DB_PATH = "bot_database.sqlite3"

def parse_color(color_val) -> discord.Color:
    """Безопасный парсинг цвета из строки (HEX) или числа в discord.Color"""
    if isinstance(color_val, discord.Color):
        return color_val
    if isinstance(color_val, int):
        return discord.Color(color_val)
    if isinstance(color_val, str):
        cleaned = color_val.strip().lstrip("#").lstrip("0x")
        try:
            return discord.Color(int(cleaned, 16))
        except (ValueError, TypeError):
            pass
    return discord.Color(COLOR_PRIMARY)
