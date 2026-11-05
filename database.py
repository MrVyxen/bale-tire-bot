import aiosqlite
from typing import Optional, Dict, Any
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                state TEXT DEFAULT 'IDLE',
                national_id TEXT,
                mobile TEXT,
                car_plate TEXT,
                car_vin TEXT,
                chassis_no TEXT,
                green_sheet_no TEXT,
                target_portal TEXT DEFAULT 'kavir',
                target_tire_size TEXT DEFAULT '185_65_14',
                tire_count INTEGER DEFAULT 2,
                sniper_enabled INTEGER DEFAULT 0,
                last_auth_token TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                action TEXT,
                status TEXT,
                message TEXT,
                latency_ms REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(chat_id: int) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def upsert_user(chat_id: int, username: str = "", **kwargs) -> Dict[str, Any]:
    user = await get_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        if not user:
            cols = ["chat_id", "username"] + list(kwargs.keys())
            vals = [chat_id, username] + list(kwargs.values())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            await db.execute(f"INSERT INTO users ({col_names}) VALUES ({placeholders})", vals)
        else:
            if kwargs:
                set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
                vals = list(kwargs.values()) + [chat_id]
                await db.execute(f"UPDATE users SET {set_clause}, last_updated = CURRENT_TIMESTAMP WHERE chat_id = ?", vals)
        await db.commit()
    return await get_user(chat_id)

async def set_state(chat_id: int, state: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET state = ? WHERE chat_id = ?", (state, chat_id))
        await db.commit()

async def get_all_active_snipers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE sniper_enabled = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def log_action(chat_id: int, action: str, status: str, message: str, latency_ms: float = 0.0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO logs (chat_id, action, status, message, latency_ms) VALUES (?, ?, ?, ?, ?)",
            (chat_id, action, status, message, latency_ms)
        )
        await db.commit()
