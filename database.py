import aiosqlite
from typing import Optional, Dict, Any, List
from config import DB_PATH

async def init_db():
    """Инициализация таблиц базы данных SQLite"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                autorole_enabled INTEGER DEFAULT 0,
                autorole_id INTEGER DEFAULT NULL,
                welcome_enabled INTEGER DEFAULT 0,
                welcome_channel_id INTEGER DEFAULT NULL,
                welcome_title TEXT DEFAULT 'Добро пожаловать!',
                welcome_message TEXT DEFAULT 'Привет новенький, {user}! Добро пожаловать на сервер **{server}**! Ты наш **{count}**-й участник.',
                welcome_color TEXT DEFAULT '#F5F3F3',
                welcome_image TEXT DEFAULT NULL,
                leave_enabled INTEGER DEFAULT 0,
                leave_channel_id INTEGER DEFAULT NULL,
                leave_message TEXT DEFAULT '{username} покинул нас. Нас осталось {count}.',
                verify_enabled INTEGER DEFAULT 0,
                verify_role_id INTEGER DEFAULT NULL,
                verify_channel_id INTEGER DEFAULT NULL,
                ticket_category_id INTEGER DEFAULT NULL,
                ticket_support_role_id INTEGER DEFAULT NULL,
                ticket_log_channel_id INTEGER DEFAULT NULL,
                ticket_counter INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP DEFAULT NULL,
                closed_by INTEGER DEFAULT NULL
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                warn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                guild_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, category, role_id)
            )
        """)

        # Автоматическая миграция: добавление новых колонок в guild_settings
        async with db.execute("PRAGMA table_info(guild_settings)") as cursor:
            rows = await cursor.fetchall()
            existing_cols = [r[1] for r in rows]

        new_columns = {
            "autorole_ids": "TEXT DEFAULT ''",
            "verify_role_ids": "TEXT DEFAULT ''",
            "ticket_support_role_ids": "TEXT DEFAULT ''",
            "ticket_panel_title": "TEXT DEFAULT 'Поддержка и создание тикетов'",
            "ticket_panel_desc": "TEXT DEFAULT 'Если у вас возник вопрос, жалоба или предложение — нажмите кнопку ниже.\nДля вас будет автоматически создан приватный канал.'",
            "ticket_panel_color": "TEXT DEFAULT '#F5F3F3'",
            "ticket_btn_label": "TEXT DEFAULT 'Создать тикет'",
            "ticket_btn_emoji": "TEXT DEFAULT '📩'",
            "ticket_inside_title": "TEXT DEFAULT 'Тикет #{number}'",
            "ticket_inside_desc": "TEXT DEFAULT 'Здравствуйте, {user}!\nОпишите ваш вопрос или проблему. Служба поддержки свяжется с вами в ближайшее время.'",
            "ticket_close_btn_label": "TEXT DEFAULT 'Закрыть тикет'",
            "ticket_transcript_btn_label": "TEXT DEFAULT 'Транскрипт'",
            "ticket_adduser_btn_label": "TEXT DEFAULT 'Добавить участника'",
            "ticket_alert_btn_label": "TEXT DEFAULT 'Позвать поддержку'"
        }

        for col_name, col_def in new_columns.items():
            if col_name not in existing_cols:
                await db.execute(f"ALTER TABLE guild_settings ADD COLUMN {col_name} {col_def}")

        await db.commit()

def parse_id_list(raw_val: Any) -> List[int]:
    """Преобразует строку с ID через запятую или одиночный int в список ID"""
    if not raw_val:
        return []
    if isinstance(raw_val, int):
        return [raw_val]
    if isinstance(raw_val, (list, tuple, set)):
        return [int(x) for x in raw_val if str(x).isdigit()]
    if isinstance(raw_val, str):
        return [int(x.strip()) for x in raw_val.split(",") if x.strip().isdigit()]
    return []

def format_id_list(id_list: List[int]) -> str:
    """Преобразует список ID в строку через запятую"""
    if not id_list:
        return ""
    return ",".join(str(x) for x in id_list)

async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
    """Получить настройки сервера. Если записи нет - создается дефолтная."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            
            # Создаем дефолтные настройки
            await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
            await db.commit()
            
            async with db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cur2:
                row2 = await cur2.fetchone()
                return dict(row2)

async def update_guild_settings(guild_id: int, **kwargs) -> Dict[str, Any]:
    """Обновить указанные поля в настройках сервера"""
    if not kwargs:
        return await get_guild_settings(guild_id)

    # Убеждаемся, что строка существует
    await get_guild_settings(guild_id)

    keys = list(kwargs.keys())
    values = list(kwargs.values())
    set_clause = ", ".join([f"{key} = ?" for key in keys])
    values.append(guild_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE guild_settings SET {set_clause} WHERE guild_id = ?", values)
        await db.commit()

    return await get_guild_settings(guild_id)

async def increment_ticket_counter(guild_id: int) -> int:
    """Увеличить счетчик тикетов сервера и вернуть новый номер"""
    settings = await get_guild_settings(guild_id)
    new_val = (settings.get("ticket_counter") or 0) + 1
    await update_guild_settings(guild_id, ticket_counter=new_val)
    return new_val

async def create_ticket(guild_id: int, channel_id: int, user_id: int) -> int:
    """Записать созданный тикет в базу"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, status) VALUES (?, ?, ?, 'open')",
            (guild_id, channel_id, user_id)
        )
        await db.commit()
        return cursor.lastrowid

async def get_ticket_by_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Получить информацию о тикете по ID канала"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_open_ticket_by_user(guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """Найти открытый тикет пользователя на сервере"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def close_ticket(channel_id: int, closed_by: int):
    """Пометить тикет как закрытый"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP, closed_by = ? WHERE channel_id = ?",
            (closed_by, channel_id)
        )
        await db.commit()

# --- Warns (Предупреждения) ---

async def add_warn(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    """Добавить варн пользователю"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason)
        )
        await db.commit()
        return cursor.lastrowid

async def get_warns(guild_id: int, user_id: int) -> List[Dict[str, Any]]:
    """Получить список варнов пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def remove_warn(warn_id: int, guild_id: int) -> bool:
    """Удалить варн по ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM warns WHERE warn_id = ? AND guild_id = ?",
            (warn_id, guild_id)
        )
        await db.commit()
        return cursor.rowcount > 0

async def clear_warns(guild_id: int, user_id: int) -> int:
    """Очистить все варны пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM warns WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        await db.commit()
        return cursor.rowcount

# --- Role Permissions (Управление доступом к командам) ---

async def add_category_role(guild_id: int, category: str, role_id: int) -> bool:
    """Добавить роль в список разрешенных для категории команд"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO role_permissions (guild_id, category, role_id) VALUES (?, ?, ?)",
            (guild_id, category, role_id)
        )
        await db.commit()
        return True

async def remove_category_role(guild_id: int, category: str, role_id: int) -> bool:
    """Удалить роль из разрешенных для категории команд"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM role_permissions WHERE guild_id = ? AND category = ? AND role_id = ?",
            (guild_id, category, role_id)
        )
        await db.commit()
        return cursor.rowcount > 0

async def get_category_roles(guild_id: int, category: str) -> List[int]:
    """Получить список ID ролей, имеющих доступ к указанной категории"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_id FROM role_permissions WHERE guild_id = ? AND category = ?",
            (guild_id, category)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def get_all_guild_permissions(guild_id: int) -> Dict[str, List[int]]:
    """Получить распределение всех ролей по категориям для сервера"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT category, role_id FROM role_permissions WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            result: Dict[str, List[int]] = {}
            for cat, rid in rows:
                if cat not in result:
                    result[cat] = []
                result[cat].append(rid)
            return result

async def clear_category_roles(guild_id: int, category: str) -> int:
    """Сбросить настройки ролей для категории (возврат к стандартным правам)"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM role_permissions WHERE guild_id = ? AND category = ?",
            (guild_id, category)
        )
        await db.commit()
        return cursor.rowcount
